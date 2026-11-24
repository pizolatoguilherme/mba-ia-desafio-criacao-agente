# Registro de validação por etapa

Cada etapa (WP) só avança depois que `scripts/validar.py --ate wpN` passa,
incluindo a regressão das etapas anteriores e os invariantes globais.

| Data | WP | Comando | Resultado | Notas / decisões |
|---|---|---|---|---|
| 2026-11-24 | WP0 | `uv run python scripts/validar.py --ate wp0` | OK (8/8) | Fork público criado; layout `src/aurora` (padrão do `uv init --package`); `google-adk==2.9.1`; teste negativo confirmou falha com `.env.example` preenchido. |
| 2026-11-24 | WP2 | `uv run python scripts/validar.py --ate wp2` | OK (14/14, regressão WP0 + invariantes) | Banco de validação isolado em diretório temporário. Teste negativo: sem o índice `ux_reserva_ativa`, 20 threads com checagem prévia criaram 20 reservas; com o índice, exatamente 1. Restauração apaga sessões e preserva `codigos_reserva`. |
| 2026-11-24 | WP3 (parcial) | `uv run python scripts/validar.py --ate wp3` | OK (16/16), 1 pulada (`llm`) | Parser com 14 capítulos; Cap. IV contém o horário de domingo e nenhuma âncora de outros capítulos. **Pendente:** checagem `--llm` do especialista (aguardando `GOOGLE_API_KEY` no `.env`). |
| 2026-11-24 | WP1 | `uv run python scripts/spike_confirmacao.py --config A` (2 execuções) | OK (7/7) | **Config A travada**: sub_agents com flags padrão de transferência, App sem `resumability_config`, `DatabaseSessionService` SQLite. Aprovação funciona após recriar Runner/SessionService. **Achado:** reenviar o mesmo FunctionResponse direto ao ADK reexecuta a tool → proteção na API (409 por `pendentes()`) + idempotência nas tools por `function_call_id` (WP4). Dependências: `google-adk[db]` e `greenlet`. Modelo: `gemini-2.5-flash` indisponível para contas novas → padrão `gemini-3.8-flash`. |
| 2026-11-24 | WP3 (concluído) | `uv run python scripts/validar.py --ate wp3 --llm` | OK (18/18), sem puladas | Especialista de regulamento responde 20h. Regressão WP0–WP2 verde. |
