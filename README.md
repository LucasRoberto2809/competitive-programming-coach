# App Framework

Aplicativo de terminal para exercitar e avaliar tecnicamente os provedores de modelos, os templates de resposta e os casos de uso do framework de programação competitiva. O app coordena uma sessão e permite repetir cenários com diferentes perfis e variantes de prompt, registrando as respostas e os resultados das verificações.

O protótipo cobre fluxos de aprendizagem e de apoio à autoria de problemas. Ele não compila nem executa o código do usuário, não atua como juiz on-line e seus testes não demonstram eficácia pedagógica.

## Configuração

Requisitos: Python 3.10+ e [uv](https://docs.astral.sh/uv/).

```powershell
uv sync
```

Os perfis de provedores ficam em `models.json`; credenciais devem ser informadas no `.env`, nunca no arquivo de perfis. Para consultar os perfis e configurar um modelo:

```powershell
uv run python -m cp_framework.models list
uv run python -m cp_framework.models add <nome> --provider <provedor> --model <id-do-modelo>
```

O app aceita perfis OpenAI-compatible — OpenRouter, OpenAI, Groq, Gemini, Mistral, DeepSeek, Ollama e endpoints customizados — e perfis do GitHub Copilot SDK. Um perfil Ollama requer o serviço local; Glow é opcional e serve apenas para formatar a saída no terminal.

## Usar e verificar provedores

Verifique o perfil selecionado antes de iniciar uma sessão. O teste envia uma chamada de conversa e outra que solicita uma resposta JSON:

```powershell
uv run python -m cp_framework.app --check
```

Para verificar todos os perfis elegíveis:

```powershell
uv run python -m cp_framework.app --check --all
```

Esses comandos fazem chamadas reais aos provedores configurados; podem consumir cota ou gerar cobrança. Perfis pagos são ignorados por padrão no teste de todos os perfis. Para autorizá-los nessa execução, use `--allow-paid`.

Inicie o app interativo com:

```powershell
uv run python -m cp_framework.app
```

## Testes de templates, guardrails e casos de uso

Execute a suíte offline:

```powershell
make test
```

O equivalente sem GNU Make é:

```powershell
uv run python -m unittest discover -s tests -t .
```

O alvo executa `unittest` para os fluxos do app, os guardrails, os templates, os perfis/provedores e o benchmark. Os testes usam provedores simulados e cenários preparados; não fazem chamadas a APIs externas. Os casos e as decisões esperadas estão documentados em [`docs/template-use-cases.md`](docs/template-use-cases.md), e os cenários automatizados estão em [`tests/test_template_use_cases.py`](tests/test_template_use_cases.py).

## Benchmark de provedores e prompts

O benchmark executa cenários do app com os perfis e variantes de prompt selecionados, aplica verificações observáveis às respostas e gera relatórios em `data/benchmarks/`.

```powershell
uv run python -m cp_framework.benchmark scenarios
uv run python -m cp_framework.benchmark estimate --profiles <perfil-a>,<perfil-b> --variants full,compact
uv run python -m cp_framework.benchmark run --profiles <perfil-a> --variants full,compact --budget-usd 1
```

Uma execução de benchmark chama os provedores reais. Confira o custo estimado antes de executar; perfis pagos exigem `--allow-paid`, e `--budget-usd` limita o orçamento configurado para a execução. Os relatórios permitem comparar os resultados dos cenários, mas não provam que uma resposta de modelo esteja correta.

Cada chamada e sessão pode gerar registros locais em `data/runs/` e `data/sessions/`; os relatórios do benchmark ficam em `data/benchmarks/`. Esses artefatos podem conter prompts, respostas e código fornecido durante os testes: não os compartilhe sem revisar seu conteúdo.
