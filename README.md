# Residencial Aurora: assistente virtual (Google ADK + FastAPI)

Assistente de chat para os moradores do Residencial Aurora. Pelo chat, o morador reserva o salão de festas, a churrasqueira e a quadra, cancela as próprias reservas, autoriza visitantes e tira dúvidas sobre o regulamento. O sistema é feito com **Google ADK 2.9.1** e modelos **Gemini**, e é exposto por uma API **FastAPI** em `http://localhost:8000`.

O modelo conduz a conversa, mas as regras críticas estão no código. Nenhuma mensagem do morador consegue furar as cinco garantias descritas abaixo.

---

## Arquitetura

```
                         POST /sessoes/{id}/mensagens · /confirmacoes
                                         │
                              src/aurora/api.py (FastAPI)
                                         │
                          src/aurora/runtime.py (Assistente)
                 App("aurora") + Runner + DatabaseSessionService (SQLite)
                                         │
                  ┌──────────── coordenador (agente principal) ────────────┐
                  │  sem tools de dados, sem o regulamento nas instruções  │
                  └──┬──────────────────────┬──────────────────────────┬──┘
        sub_agent    │           sub_agent  │                AgentTool │
       (transferência)          (transferência)          (sessão isolada)
┌────────────────────▼───┐ ┌────────────────▼────────┐ ┌───────────────▼──────────┐
│ especialista_reservas  │ │ especialista_visitantes │ │ especialista_regulamento │
│ listar_areas           │ │ listar_meus_visitantes  │ │ listar_capitulos         │
│ verificar_disponib.    │ │ autorizar_visitante  ✔  │ │ ler_capitulo             │
│ listar_minhas_reservas │ └─────────────────────────┘ └──────────────────────────┘
│ cancelar_reserva       │                ✔ = pede confirmação ao sistema
│ reservar_area        ✔ │
└────────────────────────┘
          tools ──► src/aurora/repositorio.py ──► SQLite var/aurora.db
```

### Agentes

| Agente | Responsabilidade | Como é acionado | Por quê |
|---|---|---|---|
| `coordenador` ([src/aurora/agents/coordenador.py](src/aurora/agents/coordenador.py)) | Conversa com o morador e distribui o trabalho. Não tem tools de dados nem o regulamento. | É o `root_agent` do `App`. | Mantém um contexto pequeno e barato, e cada mensagem segue para quem sabe resolver. |
| `especialista_reservas` ([src/aurora/agents/reservas.py](src/aurora/agents/reservas.py)) | Reserva, cancela e lista reservas, e informa disponibilidade. | `sub_agent` do coordenador, por **transferência**. | Reservas envolvem diálogo de vários turnos (área, data, confirmação). O especialista é **dono** das tools com confirmação, e o Runner devolve a resposta da confirmação ao último agente que falou e pode transferir. Por isso ele mantém as flags de transferência padrão. |
| `especialista_visitantes` ([src/aurora/agents/visitantes.py](src/aurora/agents/visitantes.py)) | Autoriza visitantes e lista os autorizados. | `sub_agent`, por **transferência**. | Mesmo motivo do especialista de reservas: é dono de uma tool com confirmação. |
| `especialista_regulamento` ([src/aurora/agents/regulamento.py](src/aurora/agents/regulamento.py)) | Responde dúvidas consultando o regulamento capítulo a capítulo. | `AgentTool` do coordenador. | O ADK executa o `AgentTool` numa **sessão em memória separada**. Os capítulos lidos ficam lá, e só a resposta curta volta para a conversa do morador (Garantia 4). |

A topologia e a configuração do `App` foram decididas por um spike ([scripts/spike_confirmacao.py](scripts/spike_confirmacao.py)). A combinação adotada usa sub_agents com as flags de transferência padrão (`disallow_transfer_to_parent=False`) e um `App` **sem** `resumability_config`. Com ela, a aprovação de uma confirmação chega ao agente que a pediu, inclusive com a sessão persistida em SQLite, **depois de recriar o Runner (reinício)** e com duas aprovações simultâneas. Se a resposta chegasse a outro agente, o ADK simplesmente não executaria a ação e não mostraria erro. O spike também mostrou que reenviar a mesma resposta direto ao ADK reexecuta a tool. Por isso a API recusa o reenvio com 409 e as tools têm idempotência própria.

### Armazenamento

Tudo é SQLite, em dois arquivos dentro de `var/` (fora do Git). Não há serviço externo para subir.

- `var/aurora.db` guarda o domínio: áreas, apartamentos, reservas, visitantes, o dono de cada sessão e os códigos já emitidos. O schema está em [src/aurora/db.py](src/aurora/db.py) e o acesso só passa por [src/aurora/repositorio.py](src/aurora/repositorio.py).
- `var/sessoes.db` guarda as sessões e os eventos do ADK, via `DatabaseSessionService` com `sqlite+aiosqlite`.

Os arquivos de `dados/` são só lidos. A primeira subida da API carrega os dados iniciais, e o comando de restauração volta reservas e visitantes ao estado desses arquivos. **A restauração também apaga as sessões**, para que cada avaliação comece limpa. Os códigos de reserva já emitidos continuam registrados mesmo após restaurar, para nunca se repetirem.

### Modelo

O padrão é `gemini-3.8-flash`. O `gemini-2.5-flash` não está mais disponível para contas novas do Google AI Studio. Para trocar, use `GEMINI_MODEL` no `.env`. As chamadas usam retry com backoff para erros 429 e 5xx (`src/aurora/agents/_modelo.py`).

---

## Garantias

Cada garantia abaixo aponta o arquivo e o trecho que a implementam. Todas são verificadas por [scripts/validar.py](scripts/validar.py) e pelo fluxo do avaliador em [scripts/fluxo_avaliador.py](scripts/fluxo_avaliador.py).

### 1. Cobrança ou acesso só com confirmação

- `src/aurora/tools/reservas.py` · `reservar_area`: se a área tem taxa > 0, chama `tool_context.request_confirmation(...)` e devolve `aguardando_confirmacao_do_sistema` sem gravar. Só grava quando `tool_context.tool_confirmation` chega com `confirmed=True`. Com `confirmed=False`, não grava nada. Área com taxa 0 grava direto, sem confirmação.
- `src/aurora/tools/visitantes.py` · `autorizar_visitante`: **sempre** chama `request_confirmation`, porque liberar acesso exige confirmação, e grava só com `confirmed=True`.
- `src/aurora/confirmacoes.py` · `pendentes`, `resposta`: as pendências são derivadas dos eventos persistidos (`adk_request_confirmation` sem resposta). `resposta` monta o `FunctionResponse` que retoma a tool.
- `src/aurora/runtime.py` · `responder_confirmacao`, `ConfirmacaoNaoPendente`, `enviar_texto`: só aceita um id que esteja em `pendentes()` **daquela sessão**. Qualquer outro id (inexistente, já respondido ou de outra sessão) gera `ConfirmacaoNaoPendente`, que `src/aurora/api.py` · `_confirmacao_nao_pendente` converte em **409**, e nada executa. O texto do morador sempre entra como `Part(text=...)` em `enviar_texto` e nunca vira resposta de confirmação. Enquanto houver pendência, a mensagem nova nem chega ao modelo (`AVISO_PENDENCIA`).
- `src/aurora/repositorio.py` · `_ja_executada`, `_registrar_execucao`: defesa extra. A aprovação é gravada com a chave `sessão:id da chamada` (`acoes_executadas`), e uma reexecução devolve o resultado anterior em vez de gravar de novo.

**Por que não depende do modelo:** o modelo pode chamar `reservar_area` ou `autorizar_visitante`, mas a tool só grava com `tool_confirmation.confirmed=True`. Esse valor só existe quando o ADK recebe um `FunctionResponse` de `adk_request_confirmation`, e esse `FunctionResponse` só é montado pela rota de confirmações. Escrever "já confirmei" na conversa não produz esse valor.

### 2. Cada sessão pertence a um apartamento

- `src/aurora/runtime.py` · `criar_sessao`: o apartamento é gravado **uma única vez**, na criação, no `state` da sessão ADK e na tabela `sessoes` (`repositorio.registrar_sessao`).
- `src/aurora/sessao.py` · `apartamento_da_sessao`: é a única forma de as tools obterem o apartamento. Ela exige que o `state` e a tabela `sessoes` coincidam, e se não coincidirem a operação é negada.
- `src/aurora/tools/reservas.py`, `src/aurora/tools/visitantes.py`: **nenhuma tool tem parâmetro de apartamento**. O validador confere isso no código-fonte.
- `src/aurora/repositorio.py` · `listar_reservas_ativas`, `cancelar_reserva`, `listar_visitantes`, `area_livre`: toda leitura e escrita filtra `WHERE apartamento = ?`. `cancelar_reserva` responde com uma mensagem genérica quando a reserva não é do apartamento. `area_livre` devolve **só um booleano**, nunca o dono nem o código.

**Por que não depende do modelo:** o modelo não tem como informar um apartamento, porque esse argumento não existe nas tools. O valor vem de dados gravados pela API antes de qualquer mensagem. Mesmo que o morador diga ser do 302, as consultas continuam filtradas pelo apartamento da sessão, e nenhuma tool devolve dados de outra unidade para entrarem na conversa.

### 3. Nada se perde no reinício

- `src/aurora/runtime.py` · `DatabaseSessionService`: sessões e eventos ficam em `var/sessoes.db`. Após o reinício, o mesmo `session_id` devolve os mesmos eventos e continua aceitando mensagens. Uma confirmação pendente antes do reinício também pode ser aprovada depois, o que foi testado no validador (WP5).
- `src/aurora/db.py` · `init_db`: no startup, só cria o schema e carrega os dados iniciais **se ainda não foram carregados** (`meta.seed_aplicado`). Reiniciar não reseta reservas nem visitantes.

**Por que não depende do modelo:** a persistência é do runtime e do banco. O modelo não guarda estado entre execuções, e as tools sempre leem o banco.

### 4. O regulamento é consultado, não carregado

- `src/aurora/agents/coordenador.py` · `AgentTool`: o coordenador não recebe o regulamento nas instruções. Para dúvidas, chama `especialista_regulamento` como `AgentTool`, que o ADK executa numa sessão em memória isolada.
- `src/aurora/regulamento.py` · `capitulos`, `capitulo`: divide `dados/regulamento.md` por capítulo.
- `src/aurora/tools/regulamento.py` · `listar_capitulos`, `ler_capitulo`: o especialista vê só os títulos e lê **um** capítulo por vez.

**Por que não depende do modelo:** o texto dos capítulos só existe dentro da sessão isolada do `AgentTool`. Na sessão do morador entram apenas a pergunta e a resposta curta do especialista. Mesmo que ele leia um capítulo a mais, esse texto não chega aos eventos da conversa.

### 5. Dois moradores, uma reserva

- `src/aurora/db.py` · `ux_reserva_ativa`: índice único parcial `ON reservas (area, data) WHERE status = 'ativa'`. O próprio SQLite recusa uma segunda reserva ativa para a mesma área e data **no instante do INSERT**.
- `src/aurora/repositorio.py` · `criar_reserva`, `IntegrityError`: a gravação acontece numa transação `BEGIN IMMEDIATE`. Se o índice recusar, a função devolve `{"status": "indisponivel"}`, uma resposta normal que a tool repassa e a API responde com **200**. A conferência feita antes de pedir a confirmação é só para a conversa e não é a garantia.
- `src/aurora/repositorio.py` · `codigos_reserva`: os códigos (`RSV-` + 6 hexadecimais) são registrados numa tabela que nunca é apagada. A chave primária impede reemitir qualquer código, inclusive de reserva cancelada.

**Por que não depende do modelo:** quem decide é a restrição do banco no momento da gravação, não uma checagem feita antes. Num teste com 20 gravações simultâneas, sem o índice saíram 20 reservas; com o índice saiu exatamente 1. O registro está em [VALIDACAO.md](VALIDACAO.md).

---

## Como rodar

### Pré-requisitos

- Python 3.12 ou superior (o `uv` baixa automaticamente se faltar)
- [uv](https://docs.astral.sh/uv/)
- Uma chave do [Google AI Studio](https://aistudio.google.com/apikey)

### Variáveis do `.env`

```bash
cp .env.example .env
```

| Variável | Obrigatória | Descrição |
|---|---|---|
| `GOOGLE_API_KEY` | sim | Chave do Google AI Studio |
| `GEMINI_MODEL` | não | Modelo Gemini dos agentes. Vazio usa `gemini-3.8-flash` |

### Instalar

```bash
uv sync
```

### Restaurar os dados iniciais

Rode com a API parada. O comando volta reservas e visitantes ao estado de `dados/` e apaga as sessões.

```bash
uv run aurora-restaurar
```

### Subir a API

```bash
uv run aurora-api
```

A API fica em `http://localhost:8000`. Pare com Ctrl+C e suba de novo com o mesmo comando: conversas e dados continuam lá.

### Rotas

| Método | Rota | Resposta |
|---|---|---|
| POST | `/sessoes` `{"apartamento": "101"}` | 201 `{"session_id": "..."}` |
| POST | `/sessoes/{session_id}/mensagens` `{"texto": "..."}` | 200 `{"resposta", "confirmacoes_pendentes"}` · 404 |
| POST | `/sessoes/{session_id}/confirmacoes` `{"id": "...", "confirmado": true}` | 200 (mesmo formato) · 404 · 409 |
| GET | `/sessoes/{session_id}/eventos` | 200 lista completa de eventos · 404 |
| GET | `/apartamentos/{numero}/reservas` | 200 `[{"codigo", "area", "data"}]` |
| GET | `/apartamentos/{numero}/visitantes` | 200 `[{"nome", "data"}]` |

### Validar (opcional)

```bash
# portões por etapa, com regressão (usa banco temporário e sobe a API sozinho)
uv run python scripts/validar.py --ate wp8 --llm --api

# fluxo do avaliador contra uma API já no ar
uv run aurora-restaurar && uv run aurora-api            # terminal 1
uv run python scripts/fluxo_avaliador.py --ate-12       # terminal 2
# Ctrl+C no terminal 1, `uv run aurora-api` de novo, e então:
uv run python scripts/fluxo_avaliador.py --pos-reinicio
```
