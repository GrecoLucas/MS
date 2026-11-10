# Modelação e Simulação de Bike Sharing

Simulação baseada em agentes, em Python e Mesa, de um sistema de bicicletas partilhadas numa cidade (tema 13: *Bike-Sharing System Operations and Rebalancing*). Pergunta principal: **como é que a redistribuição de bicicletas afeta a procura satisfeita, o custo e a equidade do serviço, para diferentes tamanhos da frota?**

## Estado atual

O modelo cobre as entidades e políticas do modelo conceptual (pasta `BikeSharing/`):

| Tema da proposta | No modelo |
|---|---|
| Estações e zonas de estacionamento virtuais | `StationAgent` com `kind` `station` ou `virtual` |
| Procura por local, hora, dia, meteorologia e perfil | `bike_sharing/demand.py` |
| Falta de bicicletas e de lugares | pedidos recusados, espera, desvios por estação cheia |
| Estratégias de redistribuição | `none`, `periodic`, `threshold`, `predictive` |
| Capacidade das estações e tamanho da frota | `capacity_scale`, `fleet_size`, `occupancy` |
| Incentivos de preço | `incentive_discount`, `price_unlock`, `price_minute` |
| Manutenção | avarias por km, recolha pela carrinha, oficina no depósito |
| Tempos de espera e a pé | `avg_wait_minutes`, `avg_walk_minutes` |
| Custo operacional e utilização | custos da carrinha, frota e docas; utilização de bicicletas e carrinhas |
| Equidade entre zonas urbanas | taxa de serviço por zona (`center`, `intermediate`, `periphery`) |

Há três formas de usar o modelo: linha de comandos (`main.py`), experiências com várias sementes (`experiments.py`) e duas interfaces (3D em `viz3d/`, painel Mesa em `app.py`).

## Dados

`data/stations.csv` contém 13 192 registos e 266 valores distintos de `city_id`. A cidade inicial é **442** (os nomes das estações indicam Pruszków, Polónia), com 15 estações e 183 lugares. Usam-se `id`, `name`, `lat`, `lon` e `bike_racks`. Cidades com capacidades nulas são rejeitadas.

O dataset não contém viagens, procura histórica, ocupações nem custos. **Toda a procura e todos os custos são pressupostos explícitos**, definidos em `bike_sharing/demand.py` e na classe `Economics`. Os resultados comparam cenários entre si; não preveem a operação real.

## Executar

Requer Python 3.11 ou superior. No PowerShell, na raiz do projeto:

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
```

### Um cenário

```powershell
.\venv\Scripts\python.exe main.py --days 7 --rebalancing threshold --output results/threshold
```

| Opção | Valor inicial | Significado |
|---|---|---|
| `--city` | 442 | Cidade do CSV |
| `--minutes` / `--days` | 1440 min | Duração |
| `--occupancy` | 0.5 | Fração inicial de bicicletas em cada estação |
| `--fleet-size` | — | Número total de bicicletas (substitui `--occupancy`) |
| `--capacity-scale` | 1.0 | Multiplicador da capacidade das estações |
| `--virtual-zones` | 0 | Zonas de estacionamento virtuais adicionais |
| `--demand-rate` | 0.04 | Pedidos por estação por minuto, em média |
| `--asymmetry` | 2.5 | Força dos fluxos casa-trabalho; 0 = procura uniforme e constante |
| `--weather` | dynamic | `dynamic`, `clear`, `cloudy` ou `rain` |
| `--temperature` | 15 | Temperatura média (°C) |
| `--start-weekday` | 0 | Dia inicial (0 = segunda) |
| `--rebalancing` | none | `none`, `periodic`, `threshold` ou `predictive` |
| `--vehicles` | 1 | Carrinhas de redistribuição e manutenção |
| `--vehicle-capacity` | 10 | Bicicletas por carrinha |
| `--low-threshold` / `--high-threshold` | 0.2 / 0.85 | Limiares de estação quase vazia / quase cheia |
| `--rebalance-interval` | 360 | Minutos entre rondas da política `periodic` |
| `--maintenance-threshold` | 3 | Bicicletas avariadas que desencadeiam uma recolha; 0 = sem manutenção |
| `--failure-rate` | 0.004 | Avarias por km |
| `--price-unlock` / `--price-minute` | 1.00 / 0.05 | Tarifa (€) |
| `--incentive` | 0 | Desconto (0–1) por devolver em estações com falta de bicicletas |
| `--speed-kmh` | 15 | Velocidade base de ciclismo |
| `--seed` | 42 | Semente de aleatoriedade |

Ficheiros criados em `--output`: `metrics.csv` (série temporal por minuto), `stations.csv` (totais por estação) e `summary.json` (parâmetros e indicadores).

### Experiências

```powershell
.\venv\Scripts\python.exe experiments.py --seeds 10 --days 7
```

Corre 530 simulações em paralelo (alguns minutos) e grava em `results/experiments/`:

- `runs.csv`: uma linha por simulação.
- `summary.csv`: média, desvio padrão e semi-amplitude do intervalo de confiança a 95% por cenário.
- `report.md`: tabelas prontas a copiar.
- Gráficos: `service_vs_fleet.png`, `profit_vs_fleet.png`, `equity_vs_fleet.png`, `walking_vs_fleet.png`, `cost_vs_service.png`, `sensitivity.png`.

São duas experiências: estratégia × tamanho da frota (6 estratégias × 6 frotas) e análise de sensibilidade em torno de um cenário de referência (veículos, capacidades, zonas virtuais, manutenção, preço, procura, meteorologia).

### Interface 3D

```powershell
.\venv\Scripts\python.exe -m viz3d
```

Abre http://localhost:8766 com uma cidade *low poly*: estações com as bicicletas nas docas, ciclistas e peões a circular pelas ruas, carrinha de redistribuição, depósito, ciclo dia/noite, nuvens e chuva. Precisa de ligação à internet, porque carrega o Three.js de um CDN.

- **Play/Pause** (ou barra de espaços), **+1 min** e velocidade de 1× a 240× (minutos simulados por segundo).
- **Scenario**: cenários prontos (Baseline, Threshold van, Predictive, Incentives, Small fleet, Rainy day, Virtual zones) e todos os parâmetros. As alterações aplicam-se em *Restart with these settings*.
- **Indicators**: procura satisfeita, espera, caminhada, bicicletas avariadas, custos, lucro e serviço por zona.
- Clique numa estação para ver os detalhes; duplo clique para aproximar a câmara; duplo clique no chão para voltar à vista geral.
- Cor do sinal de cada estação: verde (equilibrada), laranja (poucas bicicletas), vermelho (vazia), azul (quase cheia), roxo (cheia). Bicicletas avariadas aparecem deitadas e a vermelho. Ciclistas azuis são pendulares; laranja são ocasionais. Uma moeda dourada marca as estações com desconto ativo.

As ruas do visualizador são apenas uma forma de desenhar os movimentos: ligam cada estação às vizinhas mais próximas. O modelo calcula as distâncias em linha reta com um fator de desvio.

### Painel Mesa

```powershell
.\venv\Scripts\solara.exe run app.py
```

Abre http://localhost:8765 com o SolaraViz: mapa 2D, tabela das estações e gráficos de procura, frota e dinheiro.

## Modelo e pressupostos

Cada passo representa **um minuto**. A simulação começa numa segunda-feira às 00:00.

### Entidades

- `StationAgent`: estação ou zona virtual, com capacidade, zona urbana, bicicletas utilizáveis, bicicletas avariadas e fila de espera.
- `Bike`: cada bicicleta é um objeto com estado (`docked`, `in_use`, `in_vehicle`, `in_repair`, `in_depot`), quilómetros e condição.
- `UserAgent`: pessoa desde o pedido até devolver a bicicleta ou desistir. Tem um perfil (`commuter` ou `casual`).
- `VehicleAgent`: carrinha elétrica que redistribui bicicletas e recolhe as avariadas.
- `DepotAgent`: base das carrinhas, com oficina (2 postos, 90 minutos por reparação) e reserva de bicicletas.

### Ordem de um passo

1. Atualiza a meteorologia (de hora a hora) e a oficina.
2. Utilizadores, em ordem aleatória: devoluções, chegadas a pé, desistências.
3. Carrinhas: chegam, carregam ou descarregam, e pedem a tarefa seguinte.
4. Quem está na fila recebe as bicicletas que chegaram, por ordem de chegada.
5. Novos pedidos.
6. Medições e verificação dos invariantes.

### Procura

- Chegadas de Poisson. A taxa total é `demand_rate × estações × perfil horário × meteorologia × preço`.
- Perfil horário: dias úteis com picos às 8h e às 17h30; fins de semana com um pico ao início da tarde e 80% do volume.
- Zonas: as estações são divididas em terços pela distância ao centro. De manhã as origens concentram-se na periferia e os destinos no centro; ao fim da tarde é o inverso. É isto que desequilibra o sistema.
- Destino: proporcional à atratividade da zona e a `exp(-distância / 2 km)`.
- Meteorologia: cadeia de Markov horária (`clear`, `cloudy`, `rain`) e temperatura com ciclo diário. Chuva reduz a procura para 45% e a velocidade para 90%; o frio e o calor também reduzem a procura.
- Perfis: os pendulares são mais rápidos, esperam menos (4 min em média), andam menos a pé (até 0,6 km) e reagem pouco a preços. Os ocasionais esperam mais (8 min), andam até 1 km, fazem viagens mais longas e reagem mais a preços e descontos.
- Preço: a procura varia com a tarifa relativamente à de referência (€1,00 + €0,05/min), com elasticidade por perfil.

### Utilizadores

1. Se a estação tem bicicleta, a viagem começa.
2. Se não tem, a pessoa caminha até à estação mais próxima com bicicletas, se estiver dentro da distância aceitável.
3. Caso contrário espera na fila. Se a paciência acabar, desiste: é **procura não satisfeita**.
4. A duração da viagem depende da distância (com desvio de 1,3), da velocidade do perfil, da chuva, de ruído aleatório e, nos ocasionais, de tempo de lazer.
5. Se o destino estiver cheio, conta-se uma devolução falhada e a pessoa pedala até à estação mais próxima com lugar. Depois caminha de volta ao destino pretendido; esse tempo entra no tempo a pé.

### Avarias e manutenção

Ao terminar uma viagem, a bicicleta avaria com probabilidade `1 − exp(−failure_rate × km)`. Uma bicicleta avariada ocupa uma doca mas não pode ser alugada. As carrinhas recolhem as avariadas em qualquer paragem e fazem uma ronda dedicada quando o total atinge `maintenance_threshold`. Depois de reparadas no depósito, voltam às estações com mais falta.

### Redistribuição

Um despachante guloso atribui tarefas às carrinhas livres. As políticas diferem no nível-alvo de cada estação e em quando uma estação é considerada desequilibrada:

| Política | Quando atua | Nível-alvo |
|---|---|---|
| `none` | Nunca. A carrinha só faz manutenção e repõe bicicletas reparadas | — |
| `periodic` | Rondas de `rebalance_interval` em `rebalance_interval` minutos, para estações a 2 ou mais bicicletas do alvo | Proporcional à capacidade |
| `threshold` | Quando uma estação fica quase vazia ou quase cheia | Proporcional à capacidade |
| `predictive` | Quando o desvio ao alvo é grande | Proporcional à capacidade mais o saldo esperado de levantamentos e devoluções nas 2 horas seguintes |

### Incentivos

Com `incentive_discount > 0`, quem vai para uma estação mais cheia pode aceitar devolver numa estação próxima com falta de bicicletas, em troca do desconto. A probabilidade depende do perfil e do valor do desconto. A pessoa faz o resto do caminho a pé.

### Custos (classe `Economics`)

| Parâmetro | Valor |
|---|---|
| Carrinha: por km / por hora de trabalho / fixo por dia | €0,30 / €14 / €35 |
| Bicicleta, por dia | €0,60 |
| Doca ou lugar virtual, por dia | €0,15 |
| Reparação | €12 |

`lucro = receita − custo operacional − custo de manutenção`. Um pedido recusado só custa a receita perdida.

### Zonas virtuais

`virtual_zones` acrescenta zonas sem docas nos maiores vazios da rede (pontos médios entre estações). A procura total mantém-se; passa a repartir-se por mais locais.

## Resultados

Experiência com 10 sementes e 7 dias por simulação, frota de 50% das docas (91 bicicletas), 1 carrinha. Valores médios; os intervalos de confiança estão em `results/experiments/report.md`.

| Estratégia | Procura satisfeita | Espera (min) | A pé (min) | Diferença entre zonas | Lucro semanal (€) |
|---|---|---|---|---|---|
| Sem redistribuição | 87,4% | 0,66 | 2,76 | 0,236 | 5408 |
| Rondas periódicas | 90,9% | 0,45 | 1,28 | 0,183 | 4248 |
| Limiar | 95,1% | 0,24 | 0,60 | 0,109 | 4115 |
| Preditiva | 97,2% | 0,14 | 0,25 | 0,071 | 3789 |
| Só incentivos (50%) | 88,7% | 0,61 | 3,07 | 0,233 | 5095 |
| Limiar + incentivos | 95,5% | 0,22 | 1,11 | 0,101 | 3941 |

Leitura, sempre dentro dos pressupostos do modelo:

- A redistribuição melhora a procura satisfeita em todas as frotas. A política preditiva com 40% de frota serve tanto como a de limiar com 50%.
- A redistribuição reduz a desigualdade entre zonas: sem ela, a periferia é a zona pior servida.
- Com estes custos, **a redistribuição não se paga a si própria**: o lucro é mais alto sem ela, porque um pedido recusado só custa a receita dessa viagem.
- Aumentar a frota sem redistribuir melhora o serviço mas enche as estações: com 80% de frota, as estações estão cheias 33% do tempo e a caminhada média sobe para 6,4 minutos.
- Os incentivos sozinhos ajudam pouco (+1,3 pontos) e aumentam a caminhada.
- A capacidade da carrinha (5, 10 ou 20) quase não muda o resultado; uma segunda carrinha sobe o serviço para 97,8% mas reduz o lucro em um terço.

## Verificações

Em cada passo verifica-se:

```text
0 <= bicicletas na estação <= capacidade
estações + em viagem + nas carrinhas + no depósito = frota inicial
pedidos = levantamentos + recusados + à espera ou a caminho
levantamentos = viagens concluídas + viagens em curso
```

A meteorologia e a procura usam geradores aleatórios próprios. Com a mesma semente, dois cenários recebem exatamente os mesmos pedidos e a mesma meteorologia, pelo que as diferenças vêm só da política.

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Organização

```text
main.py                   # Um cenário pela linha de comandos
experiments.py            # Comparação de estratégias com várias sementes
app.py                    # Painel Mesa/Solara
viz3d/server.py           # Servidor do visualizador 3D
viz3d/static/             # Página, estilos e cena Three.js
bike_sharing/model.py     # Modelo, relógio, indicadores, custos e exportação
bike_sharing/agents.py    # Bicicleta, estação, utilizador, carrinha e depósito
bike_sharing/demand.py    # Perfis horários, meteorologia, perfis de utilizador e fluxos
bike_sharing/policies.py  # Políticas de redistribuição e manutenção
data/stations.csv         # Dataset original
tests/                    # Testes do modelo e do visualizador
results/                  # Resultados locais, ignorados pelo Git
```

## Limitações

1. A procura, os perfis e os custos não estão calibrados com dados reais.
2. As distâncias são em linha reta com um fator de desvio; não há rede viária.
3. As zonas urbanas são definidas pela distância ao centro, não por dados de uso do solo.
4. O encaminhamento das carrinhas é guloso, tarefa a tarefa; não há otimização de rotas.
5. A procura não satisfeita não tem custo além da receita perdida (sem perda de clientes a prazo).
6. As carrinhas trabalham a qualquer hora; não há turnos.
7. A fonte, a interpretação de `bike_racks` e a área geográfica da cidade devem ser confirmadas.

O documento conceptual original encontra-se na pasta `BikeSharing/`.
