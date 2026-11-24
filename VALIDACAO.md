# Registro de validação por etapa

Cada etapa (WP) só avança depois que `scripts/validar.py --ate wpN` passa,
incluindo a regressão das etapas anteriores e os invariantes globais.

| Data | WP | Comando | Resultado | Notas / decisões |
|---|---|---|---|---|
| 2026-11-24 | WP0 | `uv run python scripts/validar.py --ate wp0` | OK (8/8) | Fork público criado; layout `src/aurora` (padrão do `uv init --package`); `google-adk==2.9.1`; teste negativo confirmou falha com `.env.example` preenchido. |
