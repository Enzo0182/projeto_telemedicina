# TeleMed: protótipo acadêmico de telemedicina

> **Aviso:** protótipo de finalidade **acadêmica e demonstrativa**. Todos os dados são **fictícios**.
> **Não** utilize em atendimentos clínicos reais.

Fluxo demonstrado: cadastro e login → consulta de médicos e horários → agendamento → sala virtual
(sinalização WebRTC por WebSocket) → registro clínico pelo médico → histórico do paciente.

## Stack

- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic
- **Frontend:** templates Jinja2, HTML, CSS e JavaScript puro (sem frameworks)
- **Banco:** PostgreSQL 16 (extensão `btree_gist`)
- **Tempo real:** WebSocket (sinalização) + WebRTC (mídia ponto a ponto)
- **Execução:** Docker Compose

## Como executar (Docker Compose)

```bash
cp .env.example .env          # no Windows: copy .env.example .env
# edite .env e troque POSTGRES_PASSWORD (e a mesma senha em DATABASE_URL, usada fora do Docker)
docker compose up --build
```

Acesse **http://localhost:8000**.

Ao iniciar, o contêiner `app`:
1. aguarda o PostgreSQL;
2. aplica as migrações (`alembic upgrade head`);
3. popula dados fictícios se `SEED_ON_START=true` **e** o banco estiver vazio;
4. inicia o servidor (uvicorn).

### Dados fictícios

```bash
# popular (somente se o banco estiver vazio)
docker compose exec app python -m scripts.seed
# apagar tudo e recriar (os horários de demonstração são recalculados para "agora")
docker compose exec app python -m scripts.seed --reset
# função administrativa de demonstração: criar outro médico (a senha é pedida de forma interativa)
docker compose exec app python -m scripts.create_doctor --name "Dra. Exemplo" \
    --email exemplo@medico.example --specialty "Neurologia"
```

> Dica: rode `seed --reset` pouco antes de uma apresentação. Ele cria uma consulta **em andamento**
> (iniciada 10 minutos antes) entre Maria e a Dra. Ana, pronta para demonstrar a sala e o prontuário.

### Contas fictícias

Senha de todas: **`Demo@1234`** (configurável em `DEMO_PASSWORD`).

| Perfil | E-mail | Observação |
|---|---|---|
| Paciente | `maria.souza@paciente.example` | consulta em andamento com a Dra. Ana; histórico com registro do Dr. Bruno |
| Paciente | `joao.lima@paciente.example` | consulta futura com a Dra. Carla |
| Médica (Clínica Médica) | `ana.ribeiro@medico.example` | período de disponibilidade "agora" |
| Médico (Cardiologia) | `bruno.carvalho@medico.example` | |
| Médica (Dermatologia) | `carla.mendes@medico.example` | |
| Médico (Pediatria) | `diego.nogueira@medico.example` | |

## Roteiro de demonstração

Use **duas janelas isoladas** (uma normal e uma anônima, ou dois navegadores): o login usa um cookie
de sessão, então uma mesma janela comporta apenas uma conta por vez.

1. **Médico:** entre como `ana.ribeiro@…` → *Disponibilidade* → adicione um período (ex.: amanhã, 08:00–10:00).
   Os horários gerados (30 min + 5 min de intervalo) aparecem abaixo.
2. **Paciente:** entre como `joao.lima@…` → *Médicos e horários* → Dra. Ana → escolha um horário → *Confirmar*.
3. **Conflito:** abra a mesma tela de confirmação em duas janelas de pacientes diferentes e confirme nas duas.
   A segunda recebe *"Este horário não está mais disponível"*. Também é recusado agendar, com outro médico,
   um horário que se sobreponha a uma consulta que o paciente já tem.
4. **Sala:** como `maria.souza@…` e `ana.ribeiro@…`, clique em *Entrar na sala* na consulta em andamento.
   O painel *Estado da conexão* mostra sinalização, presença, estado WebRTC/ICE, câmera e microfone.
   Quando conecta, o chat P2P (canal de dados) é liberado. Com `joao.lima@…`, a mesma URL retorna *Acesso negado*.
5. **Prontuário:** na sala (ou nos detalhes da consulta), a médica clica em *Abrir registro clínico*,
   preenche e salva.
6. **Histórico:** como Maria, abra *Histórico clínico*. Os registros aparecem somente para leitura.

## Estrutura

```
app/
  main.py              # app FastAPI, middlewares (origem/CSRF, cabeçalhos) e tratamento de erros
  config.py            # configurações via variáveis de ambiente e regras de agenda
  database.py          # engine e sessão SQLAlchemy
  models.py            # modelos: User, DoctorProfile, LoginSession, AvailabilityPeriod, Appointment, ClinicalRecord
  schemas.py           # validação de formulários (Pydantic) com mensagens em português
  security.py          # hash de senha PBKDF2-SHA256, tokens de sessão e de sala
  auth.py              # login/logout, sessão por cookie e dependências de perfil (require_patient/require_doctor)
  errors.py            # exceções de domínio (403, 404, 409, 422)
  web.py               # renderização Jinja2, filtros de data e mensagens flash
  services/            # regras de negócio
    users.py           # cadastro de paciente, criação de médico, listagem
    availability.py    # períodos e geração de horários
    appointments.py    # agendamento com bloqueio e revalidação, acesso, cancelamento
    records.py         # prontuário (somente o médico responsável edita)
  routers/             # rotas HTTP e WebSocket
    auth.py  patient.py  doctor.py  appointments.py  signaling.py
  templates/           # telas Jinja2
  static/css/style.css
  static/js/room.js    # cliente WebRTC + sinalização
alembic/versions/0001_initial.py   # migração (tabelas + restrições EXCLUDE)
scripts/seed.py  scripts/create_doctor.py  scripts/start.py
Dockerfile  docker-compose.yml  .env.example
```

## Decisões de segurança e regras de negócio

- **Senhas:** PBKDF2-SHA256 com 310 mil iterações e salt aleatório (biblioteca padrão).
- **Sessão:** token aleatório em cookie `HttpOnly` e `SameSite=Lax`. O banco guarda apenas o hash SHA-256 do token,
  e o logout invalida a sessão no servidor.
- **Autorização no backend:** toda rota depende de `require_patient`, `require_doctor` ou verifica se o usuário
  é participante da consulta (`get_for_participant`). O WebSocket valida o cookie, o vínculo com a consulta e a origem.
- **CSRF:** POSTs com cabeçalho `Origin`/`Referer` de outro host são recusados, além do `SameSite=Lax`.
- **Agendamento concorrente:** as linhas do médico e do paciente são bloqueadas (`SELECT … FOR UPDATE`).
  Depois disso o backend revalida se o horário pertence à grade, está no futuro e está livre. Como garantia final,
  restrições `EXCLUDE USING gist` no PostgreSQL impedem consultas sobrepostas por médico e por paciente,
  e também períodos de disponibilidade sobrepostos.
- **Prontuário:** editável somente pelo médico responsável, de 15 minutos antes do início em diante
  ("durante ou após a consulta"). O paciente apenas visualiza.
- **Logs:** não registram senhas, tokens, mensagens de sinalização nem dados clínicos.

## Executar sem Docker (opcional)

Requer Python 3.12+ e um PostgreSQL acessível (com a extensão contrib `btree_gist`).

```bash
python -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export DATABASE_URL=postgresql+psycopg://usuario:senha@localhost:5432/telemed   # PowerShell: $env:DATABASE_URL="..."
alembic upgrade head
python -m scripts.seed
uvicorn app.main:app --reload
```

## Limitações conhecidas

- **Mídia WebRTC:** sem servidor TURN. Funciona na mesma máquina ou rede local. Em redes diferentes ou com NAT
  restritivo a conexão pode falhar, e a sala exibe um aviso em vez de simular sucesso. Configure STUN em `STUN_URLS`.
  Um TURN (ex.: coturn) não foi incluído.
- **Câmera e microfone** exigem contexto seguro: funcionam em `http://localhost`, mas para acessar de outro dispositivo
  pela rede é preciso HTTPS (proxy reverso com certificado) e `COOKIE_SECURE=true`.
- A sinalização mantém as salas **em memória**, então suporta apenas uma instância do servidor.
- A sala fica acessível aos participantes a qualquer momento enquanto a consulta estiver confirmada (sem janela de horário).
- Não há recuperação de senha, verificação de e-mail, limite de tentativas de login, notificações nem auditoria.
- O fuso horário é único para toda a aplicação (`APP_TIMEZONE`).
- Sem testes automatizados versionados no repositório (a verificação foi feita com scripts externos, descritos na entrega).
