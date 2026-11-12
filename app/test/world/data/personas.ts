// The people of the test world. Every name, employer, school and address here is invented;
// domains are example.com / example.org only.

export interface Persona {
  key: string
  name: string
  email: string
  phone: string
  city: string
  country: 'dk' | 'fr' | 'hu' | 'se'
  languages: string[]
  roleTargets: string[]
  searchKeywords: string[]
  topicTerms: string[]
  cv: string
  storyBank: string
  rawSource: string
}

const METTE_CV = `# Mette Kjær Larsen

**Phone:** +45 00 00 00 00 | **Email:** mette.kjaer.larsen@example.com | **Web:** mettekl.example.com | **Location:** Copenhagen

## Profile

Senior data scientist with nine years of experience turning messy operational and market data into forecasts and decisions that people actually use. PhD in statistics. Comfortable across the whole lifecycle: framing the question with the business, building the model, putting it into production and owning it afterwards. Known for clear communication with traders, planners and executives, and for mentoring junior data scientists.

## Work Experience

### Senior Data Scientist | Vindstrøm Energy Analytics — 2021 - present

- Lead the forecasting work stream of a seven-person data science team serving the power-trading desk.
- Built the day-ahead and intraday wind and solar production forecasts for 4.2 GW of Nordic capacity (gradient-boosted models plus a hierarchical reconciliation layer), cutting the mean absolute error by 18% against the previous vendor model.
- Designed a probabilistic price-spread model used by traders to size positions; quantified its value in a back-test at roughly EUR 3.1M a year.
- Moved the team from notebooks to a production MLOps setup: Python packages, Airflow, MLflow model registry, Docker on Kubernetes, data and drift monitoring with alerts to Slack.
- Introduced a causal-inference review for trading-strategy changes (difference-in-differences and synthetic control) so that changes are judged on effect, not anecdote.
- Mentor three data scientists; run the team's fortnightly paper and code review sessions.

### Data Scientist | Nordhavn Logistik A/S — 2018 - 2021

- Built the demand forecast for 140 distribution routes (SARIMAX, then LightGBM with calendar and weather features), used weekly by the planning department to staff warehouses.
- Reduced empty truck kilometres by 9% with an assignment model for return loads, in close collaboration with dispatch.
- Ran the company's first A/B tests on customer notifications and set up the analysis template the product team still uses.
- Built the data model in Snowflake and dbt for operational KPIs and the Power BI reports on top of it.
- Presented results monthly to the operations management group.

### Research Assistant | Institute for Applied Statistics, Øresund University — 2017 - 2018

- Developed Bayesian hierarchical models for regional electricity demand in Stan, published in a peer-reviewed journal.
- Taught the graduate course in time-series analysis (60 students).

## Education

### PhD in Statistics | Øresund University — 2017

Thesis: "Probabilistic forecasting of renewable production with hierarchical constraints". Three peer-reviewed papers; research stay at a partner institute in Edinburgh.

### MSc in Mathematics-Economics | Øresund University — 2013

Specialisation in econometrics and stochastic processes.

## Skills

Python (pandas, scikit-learn, LightGBM, PyTorch, statsmodels), SQL, R, Stan, time-series forecasting, probabilistic forecasting, causal inference, experimentation and A/B testing, optimisation (OR-Tools, Pyomo), MLOps (MLflow, Airflow, Docker, Kubernetes, GitHub Actions), Snowflake, dbt, Azure, Power BI, stakeholder management, mentoring.

## Certifications

- **Microsoft Certified: Azure Data Scientist Associate** — 2022

## Languages

- **Danish** — native
- **English** — fluent
- **Swedish** — reading
`

const METTE_STORIES = `## Cut the Wind Forecast Error by 18% at Vindstrøm Energy Analytics

**Context**: The trading desk bought its wind production forecast from an external vendor, and imbalance costs were rising as the portfolio grew past 4 GW. Build an in-house day-ahead and intraday forecast that beats the vendor and that traders trust.
**Action**: Assembled ten years of turbine, weather-model and curtailment data; trained gradient-boosted models per park and reconciled them hierarchically to portfolio level; ran the new forecast in shadow mode for three months next to the vendor's; met the traders weekly to walk through the worst days.
**Result**: Mean absolute error down 18% against the vendor; the vendor contract was not renewed, saving EUR 400k a year; imbalance costs fell measurably the following quarter.
**Learning**: The shadow period mattered more than the accuracy number — traders adopted the model because they had watched it fail and recover on real days.

## Took the Team from Notebooks to Production MLOps

**Context**: Models ran from notebooks on one laptop; two outages in a month left the desk without forecasts in the morning. Make every model reproducible, monitored and deployable by anyone on the team.
**Action**: Packaged the models, moved scheduling to Airflow, introduced an MLflow registry and Docker images on the company's Kubernetes cluster; added data-quality and drift checks with Slack alerts; wrote a one-page runbook per model.
**Result**: No missed morning forecast in the following 18 months; a new model goes from merge to production in under a day instead of two weeks.
**Learning**: The runbooks were the cheapest part and the one people thanked me for.

## Halved Empty Kilometres on Return Loads at Nordhavn Logistik

**Context**: Trucks came back from deliveries empty on a large share of routes, and dispatchers matched return loads by phone. Help dispatch find return loads systematically without changing how they worked.
**Action**: Built an assignment model in OR-Tools fed by the booking system; surfaced its suggestions in the dispatchers' existing screen; sat with the dispatch team for two weeks to tune the rules they cared about.
**Result**: Empty truck kilometres down 9% within six months; dispatchers accepted about 70% of suggestions.
**Learning**: Putting the suggestion where they already looked was worth more than any improvement to the solver.

## Brought Causal Inference into Trading-Strategy Reviews

**Context**: Strategy changes on the desk were judged by the profit of the following weeks, which mixed market luck with the change itself. Give the desk a fair way to judge whether a change worked.
**Action**: Proposed a short review template using difference-in-differences against comparable markets and synthetic control where none existed; ran the first five reviews myself and trained two analysts to run them.
**Result**: Two changes that looked profitable were shown to be market effects and rolled back; the template is now part of every strategy change.
**Learning**: Starting with the changes the traders were proudest of was risky but made the method credible.
`

const METTE_RAW = `Curriculum Vitae

METTE KJÆR LARSEN
mette.kjaer.larsen@example.com    +45 00 00 00 00
Copenhagen,  Denmark          mettekl.example.com


PROFILE
Senior data scientist ,  9 years experience. PhD in statistics.  Forecasting , causal inference and MLOps - from the question to the model in production.


EXPERIENCE

Senior Data Scientist          Vindstrøm Energy Analytics            Mar 2021 – now
  •  lead forecasting work stream in a team of 7 (power trading desk)
  •  day-ahead + intraday wind/solar forecasts for 4.2 GW ;   MAE   -18% vs vendor
  •  probabilistic price spread model, back-tested value approx EUR 3.1M / year
  •  notebooks -> production : Airflow, MLflow, Docker, Kubernetes, monitoring
  •  causal inference reviews of strategy changes (diff-in-diff, synthetic control)
  •  mentoring 3 data scientists


Data Scientist             Nordhavn Logistik A/S                 Aug 2018 – Feb 2021
  •  demand forecast for 140 routes (SARIMAX, LightGBM) - used weekly by planning
  •  return-load assignment model,   empty km  -9%
  •  first A/B tests on customer notifications
  •  Snowflake + dbt data model ;  Power BI reports


Research Assistant      Institute for Applied Statistics, Øresund University     Sep 2017 – Jul 2018
  •  Bayesian hierarchical models of regional electricity demand  (Stan)
  •  taught graduate time series course  (60 students)


EDUCATION

PhD, Statistics        Øresund University          2014 – 2017
    "Probabilistic forecasting of renewable production with hierarchical constraints"
    3 papers. Research stay, Edinburgh.

MSc  Mathematics-Economics        Øresund University       2011 – 2013


SKILLS
Python  (pandas, scikit-learn, LightGBM, PyTorch, statsmodels) ,  SQL ,  R ,  Stan
forecasting   |   causal inference   |   A/B testing   |   optimisation (OR-Tools, Pyomo)
MLflow  Airflow  Docker  Kubernetes  GitHub Actions   Snowflake  dbt  Azure  Power BI

Certificates:   Azure Data Scientist Associate (2022)

PUBLICATIONS  /  TALKS
  - Larsen M.K. et al.  "Hierarchical probabilistic forecasts for wind portfolios"  ,  journal paper   2017
  - Larsen M.K.  "Bayesian models of regional electricity demand" ,   2018
  - talk :  "From notebooks to production in a trading team"  -  Copenhagen data science meetup ,  2023
  - talk :  "Did the strategy work ? causal inference on a trading desk"   -  energy analytics conference ,  2024

OTHER
  member of the board ,  local rowing club   (2019 – 2022)
  driving licence B

LANGUAGES     Danish (native)   English (fluent)   Swedish (reading)


References available on request.
`

const LEA_CV = `# Léa Moreau

**Téléphone :** +33 6 00 00 00 00 | **Email:** lea.moreau@example.com | **Location:** Lyon

## Profil

Contrôleuse de gestion industrielle avec six ans d'expérience dans la fabrication de composants mécaniques et d'équipements médicaux. Spécialisée dans le calcul des coûts de revient, le pilotage budgétaire des sites de production et l'automatisation du reporting. Interlocutrice reconnue des directeurs d'usine et des équipes opérationnelles.

## Expérience professionnelle

### Contrôleuse de gestion industrielle | Rhodanis Mécanique — 2021 - présent

- Pilote le contrôle de gestion de deux usines (420 salariés, 95 M€ de chiffre d'affaires).
- Construit le budget annuel et les reprévisions trimestrielles avec les directeurs de site.
- Refonte du modèle de coûts standards : écarts de production expliqués à 95 % contre 70 % auparavant.
- Automatisation du reporting mensuel sous Power BI, clôture réduite de J+8 à J+5.
- Accompagnement d'un projet d'investissement de 6 M€ (dossier, suivi, analyse de rentabilité).
- Animation des revues de performance mensuelles avec les responsables de production, de la maintenance et des achats.
- Formation des chefs d'atelier à la lecture des indicateurs de coûts et de productivité.

### Contrôleuse de gestion | Alpimed Équipements — 2018 - 2021

- Analyse mensuelle des marges par gamme de produits et par client.
- Mise en place d'un suivi des stocks et des immobilisations en cours dans SAP CO.
- Participation à la migration de SAP ECC vers S/4HANA (volet contrôle de gestion) : paramétrage des centres de coûts, recette et formation de vingt utilisateurs.
- Construction du budget des frais généraux (12 M€) avec les responsables de service.
- Analyse de rentabilité des contrats de maintenance, qui a conduit à la révision de la grille tarifaire.

### Assistante contrôle de gestion (alternance) | Fonderies du Beaujolais — 2016 - 2018

- Préparation des tableaux de bord de production et des inventaires trimestriels.
- Calcul des coûts de revient des pièces de fonderie pour les devis commerciaux.
- Mémoire d'alternance sur la valorisation des en-cours de production.

## Formation

### Master Contrôle de gestion et audit organisationnel | École supérieure de gestion de Lyon — 2018

Mémoire sur la fiabilité des coûts standards dans l'industrie mécanique (mention bien).

### Licence Économie et gestion | Université Lumière-Saône — 2016

## Compétences

Contrôle de gestion industriel, coûts de revient, budget et reprévisions, analyse des écarts, SAP CO et S/4HANA, Power BI, Excel avancé (VBA, Power Query), SQL (notions), clôtures mensuelles, business partnering.

## Langues

- **Français** — langue maternelle
- **Anglais** — courant (TOEIC 905)
`

const LEA_STORIES = `## Refonte des coûts standards chez Rhodanis Mécanique

**Context**: Les écarts de production n'étaient expliqués qu'à 70 %, et les directeurs d'usine ne faisaient plus confiance aux coûts standards. Reconstruire un modèle de coûts standards fiable pour deux usines en moins d'un an.
**Action**: Revue des gammes et nomenclatures avec les méthodes ; recalcul des taux horaires par atelier ; ateliers mensuels avec chaque directeur de site pour valider les hypothèses.
**Result**: Écarts expliqués à 95 % ; deux références vendues à perte identifiées et repositionnées en prix.
**Learning**: Le temps passé avec les méthodes a été plus utile que tout outil.

## Clôture mensuelle de J+8 à J+5

**Context**: Le reporting mensuel était construit à la main dans Excel et arrivait trop tard pour le comité de direction. Réduire la clôture de trois jours sans renfort.
**Action**: Automatisation des extractions SAP avec Power Query, modèle Power BI unique, calendrier de clôture partagé avec la comptabilité.
**Result**: Clôture à J+5 en quatre mois ; le comité se tient une semaine plus tôt.
**Learning**: Le calendrier partagé a supprimé la moitié des relances.

## Suivi d'un investissement de 6 M€

**Context**: L'usine de Villefranche devait remplacer une ligne d'usinage vieillissante. Construire le dossier d'investissement et en suivre la rentabilité.
**Action**: Modèle de rentabilité sur dix ans, scénarios de volumes avec le commercial, suivi mensuel des dépenses engagées.
**Result**: Projet livré à 3 % sous budget ; retour sur investissement de 4,1 ans contre 4,5 prévus.
**Learning**: Les scénarios de volumes ont rendu la décision plus simple pour la direction.
`

const LEA_RAW = `CURRICULUM VITAE

Léa   MOREAU
lea.moreau@example.com   -   00 00 00 00 00
Lyon (69003)


Contrôleuse de gestion industrielle  -  6 ans d'expérience


EXPÉRIENCE

Sept 2021 – aujourd'hui      RHODANIS MÉCANIQUE       Contrôleuse de gestion industrielle
   - contrôle de gestion de 2 usines  (420 pers.,  CA 95 M€)
   - budget annuel + reprévisions trimestrielles
   - refonte coûts standards  :  écarts expliqués 95%  (vs 70%)
   - reporting Power BI ,  clôture J+8  ->  J+5
   - suivi investissement 6 M€

Juin 2018 – Août 2021       ALPIMED ÉQUIPEMENTS        Contrôleuse de gestion
   - marges par gamme / par client
   - stocks et immos en cours  (SAP CO)
   - migration ECC -> S/4HANA

Sept 2016 – Juin 2018      Fonderies du Beaujolais       Assistante CDG  (alternance)
   - tableaux de bord production, inventaires


FORMATION
2018    Master Contrôle de gestion et audit organisationnel  -  École supérieure de gestion de Lyon
2016    Licence Économie-Gestion   -   Université Lumière-Saône


COMPÉTENCES
SAP CO / S/4HANA      Power BI      Excel (VBA, Power Query)       SQL (notions)
coûts de revient  ,  budget ,  analyse des écarts ,   clôtures


LANGUES
Français  : maternelle         Anglais  :  courant  (TOEIC 905)

Centres d'intérêt : course à pied, chorale
`

const BENCE_CV = `# Bence Kovács

**Phone:** +36 30 000 0000 | **Email:** bence.kovacs@example.com | **Web:** github.example.com/bkovacs | **Location:** Budapest

## Profile

Backend engineer with seven years of experience building payment and logistics services in Go and Kotlin. Cares about clear APIs, boring reliable databases and observability. Has led the migration of a monolith to services and is on the on-call rotation of a high-traffic platform.

## Work Experience

### Senior Backend Engineer | Duna Payments Zrt. — 2022 - present

- Own the settlement service (Go, PostgreSQL, Kafka) that processes 2.5 million card transactions a day.
- Cut p99 latency of the authorisation API from 380 ms to 90 ms by reworking queries and connection pooling.
- Led the split of the billing monolith into four services with an outbox pattern and idempotent consumers.
- Introduced OpenTelemetry tracing and SLO-based alerting; on-call incidents dropped by a third.
- Built the reconciliation jobs that compare our ledger with the card schemes' settlement files every night.
- Run the team's architecture review and the onboarding of new backend engineers.
- Moved the team's infrastructure to Terraform and AWS EKS together with the platform team.

### Backend Engineer | Fuvar Logistics Kft. — 2019 - 2022

- Built route-planning and shipment-tracking APIs in Kotlin (Spring Boot) and PostgreSQL.
- Designed the event schema for 40,000 parcel scans an hour on RabbitMQ.
- Mentored two junior developers and ran the backend guild's code-review rotation.
- Replaced nightly batch exports to partners with a webhook service, cutting delivery-status delays from hours to seconds.
- Wrote the team's PostgreSQL migration guidelines after a schema change locked the shipments table in production.

### Junior Developer | Pixelgyár Software — 2017 - 2019

- Developed REST services in Java and Kotlin for e-commerce clients.
- Built product-catalogue import jobs and integrations with Hungarian payment providers.

## Projects

- **pgwatch-lite** — a small open-source Go tool that reports slow PostgreSQL queries and missing indexes (600 stars).
- Speaker at a Budapest Go meetup: "Idempotent consumers in practice" (2024).

## Education

### MSc in Computer Science | Budapest Technical College of Informatics — 2017

Thesis on consistency models in distributed databases.

### BSc in Software Engineering | Budapest Technical College of Informatics — 2015

## Skills

Go, Kotlin, Java, PostgreSQL, Redis, Kafka, RabbitMQ, gRPC, REST, Docker, Kubernetes, Terraform, AWS, OpenTelemetry, Prometheus, Grafana, distributed systems, event-driven architecture.

## Languages

- **Hungarian** — native
- **English** — fluent
`

const BENCE_STORIES = `## Cut Authorisation Latency from 380 ms to 90 ms at Duna Payments

**Context**: Merchants complained about slow card authorisations at peak hours; p99 latency had crept up to 380 ms. Bring p99 under 120 ms before the holiday season.
**Action**: Traced the slow path with OpenTelemetry; rewrote three N+1 queries; tuned the PostgreSQL connection pool; added a Redis cache for merchant configuration.
**Result**: p99 at 90 ms three weeks before the deadline; no timeouts during the holiday peak.
**Learning**: Tracing first saved us from optimising the wrong service.

## Split the Billing Monolith at Duna Payments

**Context**: Every billing release needed a two-hour maintenance window and broke something unrelated. Move billing to independent services without losing a single transaction.
**Action**: Carved out four services one by one; used the outbox pattern and idempotent Kafka consumers; ran old and new paths in parallel with reconciliation reports.
**Result**: Releases without downtime, from monthly to several a week; zero lost transactions during the migration.
**Learning**: The reconciliation reports were what convinced finance to let us switch over.

## Designed the Parcel-Scan Event Schema at Fuvar Logistics

**Context**: Parcel scans arrived in five formats from different depots, and tracking pages showed wrong statuses. One event schema for all depots.
**Action**: Interviewed depot leads; drafted a versioned schema; built a translation layer for legacy scanners; added contract tests.
**Result**: Wrong-status complaints down 60%; new depots onboarded in days instead of weeks.
**Learning**: Versioning from day one made the second depot trivial.
`

const BENCE_RAW = `Curriculum Vitae

Bence Kovács
Budapest  ,  Hungary
bence.kovacs@example.com      +36 30 000 0000
github.example.com/bkovacs


Senior Backend Engineer    —    Duna Payments Zrt.         Jan 2022 – now
     settlement service  (Go , PostgreSQL , Kafka) ,  2.5M transactions / day
     authorisation API  p99  380ms -> 90ms
     billing monolith -> 4 services  (outbox, idempotent consumers)
     OpenTelemetry tracing ,  SLO alerting


Backend Engineer    —    Fuvar Logistics Kft.             Sep 2019 – Dec 2021
     route planning + tracking APIs ,  Kotlin / Spring Boot ,  PostgreSQL
     event schema ,  40k scans/hour ,  RabbitMQ
     mentoring 2 juniors


Junior Developer   —   Pixelgyár Software              Jul 2017 – Aug 2019
     REST services ,  Java + Kotlin ,  e-commerce


Education
   MSc Computer Science  ,  Budapest Technical College of Informatics   (2017)
   BSc Software Engineering  ,  same   (2015)


Skills
Go   Kotlin   Java   PostgreSQL   Redis   Kafka   RabbitMQ   gRPC
Docker   Kubernetes   Terraform   AWS   OpenTelemetry   Prometheus   Grafana


Languages:    Hungarian (native) ,   English (fluent)

Hobbies:  cycling,  board games
`

const JONAS_CV = `# Jonas Berg

**Phone:** TODO | **Email:** jonas.berg@example.com

## Profile

Newly graduated environmental engineer with a focus on water and wastewater treatment. Hands-on experience from a student job at a utility and a thesis on nutrient removal. Looking for a first position in water, climate adaptation or environmental consulting.

## Work Experience

### Student Assistant | Kattegat Vand A/S — 2023 - TODO

- Took and logged samples at two treatment plants.
- Cleaned and plotted sensor data in Python for the process engineers.

### Summer Intern | Grøn Rådgivning ApS — 2022

- Helped prepare noise and soil reports for municipal clients.

## Education

### MSc in Environmental Engineering | Jutland Technical University — 2025

TODO: thesis title

### BSc in Civil and Environmental Engineering | Jutland Technical University — 2023

## Skills

Python (pandas, matplotlib), MATLAB, QGIS, AutoCAD (basic), water chemistry, laboratory analysis.

## Languages

- **Danish** — native
- **English** — fluent
`

const JONAS_STORIES = `## Cleaned Up Sensor Data at Kattegat Vand

**Context**: The process engineers had two years of oxygen and ammonium sensor logs with gaps and drift, and could not compare the two plants. Make the data usable for a comparison report.
**Action**: Wrote Python scripts to flag gaps and drift against lab samples; produced weekly plots for both plants.
**Result**: The engineers used the plots in their annual report and found an aeration setting worth changing.
**Learning**: Checking against lab samples was what made the engineers trust the cleaned series.

## Thesis on Nutrient Removal

**Context**: My thesis looked at nitrogen removal in a small rural treatment plant. Model the plant and test two control strategies.
**Action**: Built a simple model in MATLAB, calibrated it on plant data and compared the two strategies.
**Result**: One strategy cut modelled energy use by about 12% at the same effluent quality.
**Learning**: Calibration took twice as long as planned; I would start with the data next time.
`

const JONAS_RAW = `Curriculum Vitae

Jonas Berg
jonas.berg@example.com


Education
MSc Environmental Engineering,   Jutland Technical University        Sep 2023 – Jun 2025
      thesis: nitrogen removal  in a small treatment plant  (MATLAB model)
BSc Civil and Environmental Engineering ,   Jutland Technical University      2020 – 2023


Work
Student assistant      Kattegat Vand A/S              Feb 2023 – now ?
      samples at 2 treatment plants ,   python plots of sensor data

Summer intern          Grøn Rådgivning ApS            Jun 2022 – Aug 2022
      noise + soil reports for municipalities


Skills:   Python  ,  MATLAB ,  QGIS ,  AutoCAD (basic)  ,  water chemistry ,  lab work

Languages :  Danish ,  English

Other: volunteer at the local rowing club, driving licence B
`

export const PERSONAS: Record<string, Persona> = {
  mette: {
    key: 'mette',
    name: 'Mette Kjær Larsen',
    email: 'mette.kjaer.larsen@example.com',
    phone: '+45 00 00 00 00',
    city: 'Copenhagen',
    country: 'dk',
    languages: ['English', 'Danish'],
    roleTargets: ['Senior Data Scientist', 'Lead Data Scientist', 'Machine Learning Engineer', 'Forecasting Specialist'],
    searchKeywords: [
      'data scientist',
      'senior data scientist',
      'lead data scientist',
      'machine learning engineer',
      'forecasting',
      'quantitative analyst',
      'dataforsker',
      'data science',
      'mlops',
    ],
    topicTerms: ['data scien*', 'machine learning', 'forecast*', 'prognose*', 'mlops', 'quantitative', 'statistic*', 'analytics'],
    cv: METTE_CV,
    storyBank: METTE_STORIES,
    rawSource: METTE_RAW,
  },
  lea: {
    key: 'lea',
    name: 'Léa Moreau',
    email: 'lea.moreau@example.com',
    phone: '+33 6 00 00 00 00',
    city: 'Lyon',
    country: 'fr',
    languages: ['French', 'English'],
    roleTargets: ['Contrôleuse de gestion', 'Contrôleur de gestion industriel', 'Business Controller'],
    searchKeywords: [
      'contrôleur de gestion',
      'contrôleuse de gestion',
      'contrôle de gestion industriel',
      'business controller',
      'responsable contrôle de gestion',
      'analyste financier',
      'controller',
    ],
    topicTerms: ['contrôle de gestion', 'contrôleu*', 'controller', 'controlling', 'analyste financi*'],
    cv: LEA_CV,
    storyBank: LEA_STORIES,
    rawSource: LEA_RAW,
  },
  bence: {
    key: 'bence',
    name: 'Bence Kovács',
    email: 'bence.kovacs@example.com',
    phone: '+36 30 000 0000',
    city: 'Budapest',
    country: 'hu',
    languages: ['English', 'Hungarian'],
    roleTargets: ['Backend Engineer', 'Senior Backend Engineer', 'Go Developer'],
    searchKeywords: [
      'backend engineer',
      'backend developer',
      'go developer',
      'golang',
      'kotlin developer',
      'backend fejlesztő',
      'platform engineer',
    ],
    topicTerms: ['backend', 'golang', 'go developer', 'kotlin', 'platform engineer*', 'fejlesztő'],
    cv: BENCE_CV,
    storyBank: BENCE_STORIES,
    rawSource: BENCE_RAW,
  },
  jonas: {
    key: 'jonas',
    name: 'Jonas Berg',
    email: 'jonas.berg@example.com',
    phone: '',
    city: 'Aarhus',
    country: 'dk',
    languages: ['English', 'Danish'],
    roleTargets: ['Environmental Engineer', 'Graduate Engineer', 'Water Engineer'],
    searchKeywords: [
      'environmental engineer',
      'miljøingeniør',
      'graduate engineer',
      'water engineer',
      'spildevand',
      'klimatilpasning',
    ],
    topicTerms: ['environmental', 'miljø*', 'water', 'vand*', 'spildevand*', 'klimatilpasning', 'wastewater'],
    cv: JONAS_CV,
    storyBank: JONAS_STORIES,
    rawSource: JONAS_RAW,
  },
}
