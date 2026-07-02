# CatScrappy API

Backend HTTP mínimo que expõe a camada de scraping para o app mobile.
Devolve **a URL do vídeo** — quem toca/baixa é o celular.

## Rodar local

```bash
pip install fastapi "uvicorn[standard]"
uvicorn api.main:app --reload
```

Docs interativas em `http://localhost:8000/docs`.

## Endpoints

| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/healthz` | Testa se cada site responde de onde a API roda (validação do Render) |
| GET | `/sites` | Lista os sites disponíveis |
| GET | `/buscar?site=&nome=` | Busca animes por nome |
| GET | `/episodios?site=&url=` | Lista episódios (passe `url_detalhes`) |
| GET | `/extrair-video?site=&url=` | Resolve a URL do vídeo (passe `url_pagina`) |

`site` = `topanimes` ou `animesdrive`.

## Deploy no Render

O `render.yaml` na raiz já configura o serviço. Conecte o repositório no
Render (Blueprint) e faça o deploy.

## O teste de viabilidade

Depois do deploy, acesse `https://SEU-APP.onrender.com/healthz`.

- Se todos os sites vierem `{"ok": true}`, o IP do datacenter **não** está
  bloqueado — pode seguir para o app React Native.
- Se vierem `{"ok": false, ...}`, o Render não consegue acessar os sites.
  Nesse caso, use a alternativa de rodar o backend no PC local + Tailscale.
