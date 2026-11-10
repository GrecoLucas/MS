# Modelação e Simulação de Bike Sharing

Simulação baseada em agentes, em Python e Mesa, de uma única cidade. Pergunta principal: **como é que a redistribuição de bicicletas afeta a procura satisfeita, para diferentes tamanhos da frota?**

## Estado atual

Cenário inicial sem redistribuição: estações reais, pedidos sintéticos, viagens e devoluções. Ainda não inclui veículos, manutenção, preços, meteorologia ou interface gráfica.

## Dados

`data/stations.csv` contém 13 192 registos e 266 valores distintos de `city_id`. A cidade inicial é **442**, com 15 estações e soma de `bike_racks` de 183. Todas têm capacidade positiva.

Usam-se `id`, `name`, `lat`, `lon` e `bike_racks`. A interpretação de `bike_racks` como capacidade e a identidade/área geográfica da cidade devem ser confirmadas na fonte. Cidades com capacidades nulas são rejeitadas até revisão dos dados.

O dataset não contém viagens, procura histórica ou ocupações. Os resultados são cenários com pressupostos, ainda sem calibração para prever a operação real.

## Executar

Requer Python 3.11 ou superior. No PowerShell, na raiz do projeto:

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe main.py
```

Se `venv` já existir, não é necessário recriá-lo. Usa-se Mesa 3.3.1, a versão presente no ambiente inicial.

```powershell
.\venv\Scripts\python.exe main.py --city 442 --minutes 1440 --occupancy 0.5 --demand-rate 0.02 --speed-kmh 15 --seed 42 --output results/baseline
```

| Opção | Valor inicial | Significado |
|---|---|---|
| `--city` | 442 | Cidade do CSV |
| `--minutes` | 1440 | Duração em minutos |
| `--occupancy` | 0.5 | Fração inicial de bicicletas em cada estação |
| `--demand-rate` | 0.02 | Pedidos por estação por minuto, em média |
| `--speed-kmh` | 15 | Velocidade constante assumida |
| `--seed` | 42 | Semente de aleatoriedade |
| `--output` | results/baseline | Diretório de saída |

Reutilizar um diretório de saída substitui os resultados anteriores. Para comparar cenários, escolhe diretórios diferentes.

## Modelo e pressupostos

- `BikeSharingModel`: relógio, geração de pedidos e recolha com `DataCollector`.
- `StationAgent`: localização, capacidade, bicicletas e métricas locais.
- `UserAgent`: viagem ativa transportando uma bicicleta; removido após devolução. Pedidos recusados são contados sem agentes persistentes.
- As bicicletas são contadores nas estações e estão associadas aos utilizadores em viagem; não são agentes individuais.

Cada passo representa **um minuto**. Processam-se primeiro as devoluções previstas, em ordem aleatória; depois os pedidos nas estações, também em ordem aleatória. Por fim medem-se ocupações e verificam-se invariantes. Uma bicicleta devolvida pode ser levantada no mesmo passo.

1. Bicicletas iniciais por estação: `int(capacidade * occupancy)`. O arredondamento é para baixo em cada estação.
2. Pedidos seguem uma distribuição de Poisson com taxa constante e igual para todas as estações. O valor inicial equivale a 1,2 pedidos por estação por hora.
3. Sem bicicleta, o utilizador desiste imediatamente. Não existem filas nem métricas de espera para levantamento.
4. Destino uniforme entre as outras estações.
5. Viagem calculada por distância geográfica em linha reta e velocidade constante, arredondada para cima, com mínimo de um minuto. Não usa rede viária.
6. Se o destino estiver cheio, conta-se uma tentativa falhada e segue-se para a estação mais próxima com espaço naquele instante. Não há reserva de lugar.
7. Se todas estiverem cheias, tenta-se novamente no destino um minuto depois. Uma viagem pode ter várias tentativas falhadas.
8. Viagens em curso no final permanecem em curso; não se força a devolução.

A procura uniforme é apenas uma base. Antes de avaliar redistribuição, devem ser introduzidos períodos de maior procura e fluxos assimétricos entre estações.

## Resultados e verificações

São criados três ficheiros:

- `metrics.csv`: série temporal com estado inicial no minuto zero; pedidos e falhas acumulados, viagens concluídas, bicicletas em uso e estações vazias/cheias.
- `stations.csv`: coordenadas, capacidade, bicicletas finais, pedidos, levantamentos, falhas e minutos vazia/cheia por estação.
- `summary.json`: parâmetros e resumo; `service_rate` é a fração de pedidos com levantamento bem-sucedido, ou `null` se não existirem pedidos.

O tempo vazio/cheio é observado no fim de cada minuto. As falhas de devolução contam tentativas, não utilizadores distintos. `served` conta levantamentos, não viagens concluídas.

Em cada passo verifica-se:

```text
0 <= bicicletas na estação <= capacidade
bicicletas nas estações + bicicletas em viagem = frota inicial
pedidos = levantamentos satisfeitos + pedidos recusados
levantamentos satisfeitos = viagens concluídas + viagens em curso
```

Executar os testes:

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Organização

```text
main.py                 # Comandos e resumo da execução
bike_sharing/model.py   # Modelo, agentes e exportação
data/stations.csv       # Dataset original
data/DataAnalysis.py    # Análise exploratória original
tests/test_model.py     # Verificações do modelo
requirements.txt        # Dependências
results/                # Resultados locais, ignorados pelo Git
```

## Próximas etapas

1. Confirmar a fonte, capacidades e área geográfica escolhida.
2. Introduzir procura por estação/período e probabilidades origem-destino.
3. Adicionar um veículo com capacidade e tempos de deslocação explícitos.
4. Comparar ausência de redistribuição, horários fixos e limiares de ocupação, mantendo procura e frota iguais.
5. Variar a frota e repetir experiências com várias sementes, apresentando médias e variabilidade.
6. Acrescentar visualização, custos e manutenção conforme a pergunta de investigação.

O documento conceptual original encontra-se na pasta `BikeSharing/`.
