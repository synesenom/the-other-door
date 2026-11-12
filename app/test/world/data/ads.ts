// The job ads of the test world. Every employer, contact person and address is invented;
// links use .example hosts only.

export type Site = 'jobindex' | 'thehub' | 'jobbank' | 'greenhouse' | 'lever' | 'francetravail' | 'manual'

export interface Ad {
  key: string
  persona: string
  site: Site
  title: string
  titleEn?: string
  company: string
  location: string
  language: 'en' | 'da' | 'fr' | 'hu' | 'sv'
  description: string
  applyUrl?: string
  postedDaysAgo: number
  score: number | null
  reason: string
  matching: string[]
  missing: string[]
  fresh?: boolean
}

export const ADS: Ad[] = [
  // ---------------------------------------------------------------- mette: strong
  {
    key: 'vestvind-senior-ds-forecasting',
    persona: 'mette',
    site: 'greenhouse',
    title: 'Senior Data Scientist, Production Forecasting',
    company: 'Vestvind Service A/S',
    location: 'Aarhus',
    language: 'en',
    description: `Vestvind Service keeps more than 6,000 wind turbines turning in eleven countries. Our customers are utilities and investors who pay us for availability, and every hour a turbine stands still costs them money and costs the climate clean power. Behind our service technicians stands a fast-growing digital organisation in Aarhus that turns sensor data from the fleet into decisions: when to send a crew, which component to replace before it fails, and how much energy a park will deliver tomorrow and next year.

We are now looking for a Senior Data Scientist to join the Production Forecasting team. The team is six people today: four data scientists, a data engineer and a product owner who used to run a service region. We sit with the Performance Engineering department and work directly with the commercial team that writes our availability and production guarantees.

The role

Our production forecasts are used in two ways. Short-term, our customers' trading desks and our own planners use day-ahead and intraday forecasts to plan maintenance windows in low-wind periods. Long-term, the commercial team uses our yield models to price contracts that run for fifteen years. Both forecasts were built quickly while the company grew, and both now need a careful second generation.

You will take the lead on the short-term forecast. That means owning the modelling choices, but also the conversations with the people who use it. You will be the person who can explain to a site manager why the forecast was wrong last Tuesday, and to our CFO what an extra percentage point of accuracy is worth.

Responsibilities

- Design and build the next generation of our day-ahead and intraday production forecasts for single turbines, parks and portfolios.
- Move from point forecasts to probabilistic forecasts, and make sure the uncertainty is understood and used by planners.
- Reconcile forecasts across turbine, park and portfolio levels so that the numbers add up.
- Bring the models into production together with our data engineer, using our existing stack: Python, Databricks, MLflow, Azure DevOps and Kubernetes.
- Set up monitoring that tells us when a model drifts before a customer tells us.
- Work with Performance Engineering on curtailment, icing and wake effects, which today are handled by rules of thumb.
- Coach the two less experienced data scientists in the team and take part in code reviews.

What you bring

- Five or more years of hands-on experience with time-series forecasting in production, ideally in energy, utilities or another domain where the weather matters.
- A strong statistical foundation. A PhD or similar research background is welcome but not required.
- Solid Python and SQL. You write code that others can read, test and run without you.
- Experience with gradient-boosted models and with at least one probabilistic method (quantile regression, conformal prediction, ensembles or Bayesian models).
- Practical MLOps experience: model registries, scheduled pipelines, monitoring.
- The ability to explain technical results to people who do not care about the method, only about the result.
- Fluent English. Danish is a plus but not a requirement; about a third of the team does not speak Danish.

Nice to have

- Experience with numerical weather prediction data (ECMWF or similar) and its quirks.
- Knowledge of power markets and how imbalance costs arise.
- Experience with hierarchical forecast reconciliation.

What we offer

You will join a company where data science has a direct line to the bottom line and where your models are used every morning. We are a technical company at heart: our managers have been technicians and engineers, and they ask good questions.

- A permanent position with a competitive salary and a pension scheme of 12% (employer 8%, employee 4%).
- Flexible working hours and two days a week from home, as agreed with the team.
- Health insurance, a canteen with a green focus, and a sports association with everything from padel to sailing.
- A yearly budget for conferences and courses, and time to go deep on hard problems.
- The chance to visit a wind park and climb a turbine with our technicians, if you wish.

Our office is on the harbour front in Aarhus, ten minutes' walk from the train station. Some travel to our sites and to the Hamburg office will occur, around five days a year.

About the recruitment process

We review applications continuously and will close the position when we have found the right person, so apply soon. The process consists of a first conversation with the hiring manager, a technical conversation about a forecasting problem from your own past (no take-home test), and a final meeting with the team and the head of Performance Engineering. We will ask for references at the end.

Questions about the position are welcome. Contact Head of Production Forecasting Søren Bach Nygaard at +45 00 00 00 00, or Talent Partner Ida Rask Holm at +45 00 00 00 00.

Application deadline: 30 November 2026.

Vestvind Service A/S is an equal-opportunity employer. We welcome applications from all qualified candidates regardless of gender, age, ethnicity, religion, disability or sexual orientation.`,
    postedDaysAgo: 3,
    score: 0.91,
    reason: 'Her day-ahead and intraday wind forecasts for 4.2 GW at Vindstrøm, with hierarchical reconciliation and an MLflow/Airflow production setup, are almost exactly this role. Only Databricks is not on her CV.',
    matching: ['time-series forecasting', 'probabilistic forecasting', 'Python', 'MLOps', 'mentoring'],
    missing: ['Databricks'],
  },
  {
    key: 'fjordpension-senior-ds',
    persona: 'mette',
    site: 'jobindex',
    title: 'Senior Data Scientist til investeringsområdet',
    titleEn: 'Senior Data Scientist for the investment area',
    company: 'Fjordpension',
    location: 'Copenhagen',
    language: 'da',
    description: `Har du lyst til at bruge data science til at skabe bedre pensioner for 410.000 medlemmer? Så er du måske vores nye Senior Data Scientist.

Fjordpension forvalter 190 mia. kr. for medlemmer inden for undervisning, sundhed og den offentlige sektor. Vores investeringsafdeling har de seneste år bygget et Quant & Data-team op, som i dag tæller fem medarbejdere. Teamet udvikler modeller for afkast, risiko og likviditet og understøtter porteføljeforvalterne med analyser, der går ud over de klassiske nøgletal.

Dine opgaver

- Udvikle og vedligeholde prognosemodeller for likviditet og pengestrømme på tværs af porteføljen.
- Bygge modeller, der kan forklare, hvad der driver afkastet i vores unoterede investeringer.
- Gennemføre analyser af effekten af investeringsbeslutninger med solide statistiske metoder.
- Sætte modeller i drift sammen med vores dataingeniører på Azure og sørge for overvågning.
- Formidle resultater til porteføljeforvaltere og investeringsdirektion på en klar og troværdig måde.

Vi forventer, at du

- har en kandidat- eller ph.d.-grad i statistik, matematik-økonomi, fysik eller lignende
- har mindst fem års erfaring med data science, gerne med tidsrækker og prognoser
- er stærk i Python og SQL og trives med at skrive kode, som andre kan bygge videre på
- har erfaring med kausal inferens eller anden metode til at skelne effekt fra tilfældigheder
- kan lide at tale med forretningen og omsætte deres spørgsmål til analyser
- taler og skriver dansk og engelsk

Erfaring fra den finansielle sektor er en fordel, men ikke et krav. Vi lægger mere vægt på din metodiske tyngde og din lyst til at lære investeringsområdet.

Vi tilbyder

En stilling i et fagligt stærkt miljø med stor indflydelse på, hvordan data bruges i investeringsbeslutninger. Du får gode muligheder for efteruddannelse, fleksible arbejdstider med mulighed for hjemmearbejde to dage om ugen, frokostordning, motionsfaciliteter og en pensionsordning, som du nok kan gætte, er god. Løn efter kvalifikationer.

Vores kontor ligger ved Kalvebod Brygge med fem minutters gang til Dybbølsbro Station.

Vil du vide mere?

Kontakt Head of Quant & Data Anders Holmgaard Krog på telefon 00 00 00 00. Ansøg via linket senest den 24. november 2026. Vi holder samtaler løbende.`,
    applyUrl: 'https://job.fjordpension.example/stillinger/senior-data-scientist-investering',
    postedDaysAgo: 6,
    score: 0.84,
    reason: 'Her PhD in statistics, five-plus years of forecasting and the causal-inference reviews she introduced on the trading desk fit the liquidity forecasts and effect analyses asked for. No pension or asset-management experience, which the ad calls a plus only.',
    matching: ['forecasting', 'causal inference', 'Python', 'SQL', 'Azure', 'stakeholder management'],
    missing: ['asset management'],
  },
  {
    key: 'baltic-power-lead-ds',
    persona: 'mette',
    site: 'lever',
    title: 'Lead Data Scientist, Energy Trading',
    company: 'Baltic Power Trading ApS',
    location: 'Copenhagen (hybrid)',
    language: 'en',
    description: `Baltic Power Trading is an independent energy trading house with 140 people in Copenhagen, Tallinn and Oslo. We trade power and gas in the Nordic and Baltic markets and optimise flexible assets — batteries, hydro and demand response — for asset owners who want more out of them.

Our analytics team of eleven builds the models our traders rely on every day: fundamental and statistical price forecasts, production forecasts for the renewable assets we manage, and the optimisation engine that bids our batteries into the balancing markets. We are now creating a Lead Data Scientist role to set the technical direction of the team.

What you will do

- Lead the data science work across price, production and load forecasting, setting priorities with the Head of Analytics and the desk heads.
- Raise the bar for how we build, review, test and deploy models.
- Build probabilistic forecasts that feed directly into position sizing and battery bidding.
- Own the evaluation framework that tells us whether a model change is worth its cost.
- Hire and mentor data scientists; the team will grow by three people in 2027.

What you bring

- Seven or more years of experience with forecasting models in production, of which several in energy or commodities.
- Deep statistical knowledge and a pragmatic attitude to model choice.
- Strong Python; experience with modern MLOps tooling (we use Airflow, MLflow, Docker and Kubernetes on Azure).
- A record of working closely with traders or other demanding end users.
- Experience leading or mentoring other data scientists.

We offer

A senior role with real influence in a flat organisation, a competitive base salary and a yearly bonus tied to the company's results, 10% pension, lunch scheme, and a hybrid setup where most of the team works from the office Tuesday to Thursday. Our office is in Nordhavn, close to the metro.

How to apply

Please apply through our careers site with your CV and a few lines on a forecasting problem you are proud of. We interview continuously. Questions: Head of Analytics Kristoffer Vang, kristoffer.vang@balticpower.example.`,
    applyUrl: 'https://careers.balticpower.example/jobs/lead-data-scientist-energy-trading',
    postedDaysAgo: 2,
    score: 0.94,
    reason: 'She already leads the forecasting work stream for a power-trading desk at Vindstrøm, built a probabilistic price-spread model used for position sizing, and runs the same Airflow/MLflow/Kubernetes stack. Mentoring three data scientists covers the lead part.',
    matching: ['probabilistic forecasting', 'power trading', 'MLOps', 'Python', 'Azure', 'mentoring'],
    missing: [],
  },
  {
    key: 'kronvej-ml-engineer-mlops',
    persona: 'mette',
    site: 'thehub',
    title: 'Machine Learning Engineer, MLOps',
    company: 'Kronvej',
    location: 'Copenhagen',
    language: 'en',
    description: `Kronvej is a Copenhagen fintech that helps small businesses get paid faster. Our invoice financing product has grown to 18,000 customers in Denmark, Sweden and Finland since our Series B last year, and every decision we make — who we finance, at what price, and how much — is made by models.

We are 85 people, of which 30 in engineering. Our ML team is four people today, and we are looking for an ML Engineer who loves taking models from a notebook to a robust service.

What you'll work on

- Our model platform: training pipelines, feature store, model registry and the serving layer that answers 40 credit decisions a second.
- Monitoring of data quality, drift and model performance, with alerts the on-call engineer can act on.
- Close work with our data scientists on credit-risk and cash-flow forecasting models.
- Helping the rest of engineering understand and trust what ML does.

Our stack

Python, PostgreSQL, Snowflake, dbt, Airflow, MLflow, Docker, Kubernetes on GCP, GitHub Actions, Grafana.

You probably have

- 4+ years of experience building data or ML systems in production.
- Solid software engineering habits: tests, code review, CI/CD.
- Experience with containerised deployments and at least one workflow orchestrator.
- Enough modelling knowledge to have a good conversation with a data scientist.

Bonus: experience with credit risk, GCP or real-time feature serving.

What we offer

Competitive salary plus warrants, 6 weeks of vacation, pension, lunch, a yearly learning budget of DKK 15,000, and an office in Kødbyen. We work hybrid with two fixed office days.

Apply via The Hub with your CV. We reply to everyone within a week.`,
    postedDaysAgo: 8,
    score: 0.82,
    reason: 'She moved her team from notebooks to Airflow, MLflow, Docker and Kubernetes with drift monitoring, and has Snowflake and dbt from Nordhavn Logistik. Credit risk, GCP and real-time serving are new to her.',
    matching: ['MLOps', 'Airflow', 'MLflow', 'Kubernetes', 'Snowflake', 'dbt'],
    missing: ['GCP', 'credit risk', 'real-time feature serving'],
  },
  {
    key: 'nordisk-elnet-prognose',
    persona: 'mette',
    site: 'jobindex',
    title: 'Senior Data Scientist til prognoser for elsystemet',
    titleEn: 'Senior Data Scientist for power system forecasts',
    company: 'Nordisk Elnet',
    location: 'Odense',
    language: 'da',
    description: `Den grønne omstilling betyder, at elsystemet skal håndtere langt mere vind- og solenergi end i dag. Det stiller nye krav til de prognoser, vi bruger til at holde balancen i nettet hvert eneste minut. Vil du være med til at bygge dem?

Om os

Nordisk Elnet ejer og driver transmissionsnettet i Syddanmark og har 600 medarbejdere. I afdelingen Systemanalyse arbejder 22 ingeniører, økonomer og dataspecialister med prognoser, markedsanalyser og planlægning af nettet. Prognoseteamet består i dag af fire personer og leverer forbrugs-, produktions- og tabsprognoser til kontrolrummet.

Jobbet

Du bliver teamets faglige spydspids inden for maskinlæring og sandsynlighedsbaserede prognoser. Du skal blandt andet:

- videreudvikle vores prognoser for vind- og solproduktion og elforbrug fra timer til uger frem
- indføre sandsynlighedsbaserede prognoser, som kontrolrummet kan bruge til at vurdere risici
- sikre at prognoserne hænger sammen på tværs af net-områder og tidshorisonter
- sætte modeller i drift og overvåge dem sammen med vores IT-afdeling
- dele din viden med kolleger og være med til at ansætte nye profiler

Din profil

Du har en relevant kandidat- eller ph.d.-uddannelse og flere års erfaring med tidsrækkemodeller og maskinlæring. Du programmerer sikkert i Python, har erfaring med at sætte modeller i produktion, og du kender til energisektoren eller har lyst til at lære den grundigt at kende. Du kan formidle komplekse resultater til både ingeniører i kontrolrummet og ledelsen. Du taler og skriver dansk.

Vi tilbyder

En meningsfuld stilling med direkte betydning for forsyningssikkerheden og den grønne omstilling. Ansættelse efter overenskomst med pension, fleksibel arbejdstid, mulighed for hjemmearbejde og et uformelt miljø med høj faglighed. Arbejdspladsen er i Odense, tæt på banegården.

Kontakt og ansøgning

Har du spørgsmål, så ring til teamleder Lone Fjeldsø på 00 00 00 00. Søg stillingen via vores karriereside senest den 21. november 2026. Første samtaler holdes i uge 48.`,
    applyUrl: 'https://karriere.nordisk-elnet.example/job/senior-data-scientist-prognoser',
    postedDaysAgo: 5,
    score: 0.88,
    reason: 'Her PhD thesis on probabilistic forecasting of renewable production with hierarchical constraints and her production forecasts at Vindstrøm match the wind, solar and load forecasts here. The role is in Odense rather than Copenhagen.',
    matching: ['probabilistic forecasting', 'time-series forecasting', 'Python', 'MLOps', 'energy'],
    missing: [],
  },
  {
    key: 'torvehal-demand-forecasting',
    persona: 'mette',
    site: 'greenhouse',
    title: 'Senior Data Scientist, Demand Forecasting',
    company: 'Torvehal Dagligvarer A/S',
    location: 'Copenhagen (hybrid)',
    language: 'en',
    description: `Torvehal Dagligvarer runs 430 supermarkets across Denmark and a fast-growing online grocery service. Every night, our systems decide how much of 22,000 products to send to each store. Too little and customers leave empty-handed; too much and food goes to waste. Our Data & AI team of 35 people builds the forecasts and optimisation behind those decisions.

We are looking for a Senior Data Scientist for the Demand Forecasting squad, which owns the store-level sales forecast. The squad has five data scientists, two ML engineers and a product manager.

Your responsibilities

- Improve the accuracy of our daily store-by-product forecast, especially for fresh products, campaigns and holidays.
- Model the effect of weather, local events and price changes on demand.
- Run controlled experiments with store groups to measure the business impact of forecast changes.
- Contribute to our forecasting platform (Python, LightGBM, Spark on Azure, MLflow) and its monitoring.
- Mentor colleagues and help shape the squad's roadmap with the product manager.

Who you are

- You have 5+ years of experience with demand or sales forecasting at scale.
- You are fluent in Python and SQL and know the gradient-boosting toolbox well.
- You understand experimental design and can tell a real improvement from noise.
- You enjoy working with operational people — store managers, buyers and supply chain planners.

We offer

A role where your work reduces food waste measurably, a modern data platform, hybrid work with two office days at our headquarters in Valby, pension, health insurance, an employee discount in all our stores and a strong learning culture with internal tech talks every Friday.

Apply by 28 November 2026. Contact: Lead Data Scientist Rikke Dam, +45 00 00 00 00.`,
    postedDaysAgo: 4,
    score: 0.86,
    reason: 'Her LightGBM demand forecast for 140 routes at Nordhavn Logistik, used weekly by planners, plus her A/B testing work fit the store-level forecast and the experiments. She has not worked in retail or with Spark.',
    matching: ['demand forecasting', 'LightGBM', 'Python', 'SQL', 'A/B testing', 'mentoring'],
    missing: ['Spark', 'retail'],
  },
  {
    key: 'sundline-network-optimisation',
    persona: 'mette',
    site: 'lever',
    title: 'Senior Data Scientist – Network Optimisation & Demand Forecasting Team',
    company: 'Sundline Shipping',
    location: 'Copenhagen',
    language: 'en',
    description: `Sundline Shipping operates 48 container and ro-ro vessels on short-sea routes in Northern Europe, connecting 30 ports from Gdańsk to Rotterdam. Our Commercial Analytics department helps the business decide which routes to sail, how to price capacity and how to position empty containers.

About the team

The Network Optimisation & Demand Forecasting team is eight people: data scientists, an operations research specialist and two analysts. We are now looking for a Senior Data Scientist who can strengthen both sides of the team's name.

Responsibilities

- Build and improve weekly and monthly volume forecasts per lane and cargo type.
- Develop optimisation models for empty-container repositioning together with our OR specialist.
- Quantify the impact of commercial initiatives with sound causal methods.
- Bring models into production on our Azure and Databricks platform.
- Present findings to commercial and operations leadership.

Requirements

- MSc or PhD in statistics, operations research, econometrics or similar.
- 5+ years of experience with forecasting and optimisation in logistics, transport or supply chain.
- Strong Python and SQL; experience with solvers such as OR-Tools, Gurobi or Pyomo.
- Excellent communication skills in English.

We offer

A dynamic international environment, competitive salary, bonus, pension, health insurance and modern offices at Langelinie. Travel is limited to a few days a year.

Application deadline: 1 December 2026. Contact Head of Commercial Analytics Peter Juul Brandt on +45 00 00 00 00.`,
    applyUrl: 'https://jobs.sundline.example/apply/senior-ds-network-optimisation',
    postedDaysAgo: 9,
    score: 0.81,
    reason: 'She built route demand forecasts and an OR-Tools assignment model for return loads at Nordhavn Logistik, which maps closely onto lane forecasts and empty-container repositioning. Databricks and shipping are new.',
    matching: ['demand forecasting', 'optimisation', 'OR-Tools', 'causal inference', 'Python'],
    missing: ['Databricks', 'Gurobi'],
  },
  {
    key: 'pakkepost-causal-experimentation',
    persona: 'mette',
    site: 'greenhouse',
    title: 'Senior Data Scientist, Experimentation & Causal Inference',
    company: 'Pakkepost Norden',
    location: 'Copenhagen',
    language: 'en',
    description: `Pakkepost Norden delivers 300,000 parcels a day to homes and parcel lockers in Denmark and Sweden. As we roll out new delivery options, pricing and customer notifications, we need to know what actually works — and our Data Science chapter is responsible for answering that question rigorously.

The role

As Senior Data Scientist for Experimentation & Causal Inference, you will own the methods we use to evaluate change. Many of our changes cannot be randomised at customer level — a new locker network, a new depot, a price change in one region — so we need someone who is at home with quasi-experimental methods as well as classic A/B tests.

You will

- Design experiments and quasi-experiments with product and operations teams.
- Build and maintain our experimentation library in Python and the analysis templates on top of it.
- Run difference-in-differences, synthetic control and regression discontinuity analyses where randomisation is not possible.
- Teach colleagues to frame questions causally.

You have

- 5+ years of experience with experimentation and causal inference in an industry setting.
- Strong statistics and Python; SQL on large datasets (we use Snowflake and dbt).
- Experience presenting results to non-technical stakeholders and changing decisions with them.
- Experience from logistics or e-commerce is a plus.

We offer

Hybrid work, a modern office at Sydhavnen, pension, health insurance, free parcel lockers for life (yes, really), and a team that loves good methodology.

Apply by 25 November 2026. Questions to Chapter Lead Maja Thorsager, maja.thorsager@pakkepost.example.`,
    postedDaysAgo: 11,
    score: 0.83,
    reason: 'She introduced difference-in-differences and synthetic control reviews at Vindstrøm, ran the first A/B tests at Nordhavn Logistik and knows Snowflake and dbt; the logistics background is a plus here.',
    matching: ['causal inference', 'A/B testing', 'Python', 'Snowflake', 'dbt', 'stakeholder management'],
    missing: ['regression discontinuity'],
  },

  // ---------------------------------------------------------------- mette: medium
  {
    key: 'torvehal-pricing-promotions',
    persona: 'mette',
    site: 'greenhouse',
    title: 'Data Scientist, Pricing & Promotions',
    company: 'Torvehal Dagligvarer A/S',
    location: 'Copenhagen (hybrid)',
    language: 'en',
    description: `Torvehal Dagligvarer runs 430 supermarkets across Denmark. Each week we run more than 1,500 promotions, and each one is a bet: will it bring new customers into the store, or just move sales from one week to another?

Our Pricing & Promotions squad, part of the Data & AI team, builds the models that help category managers answer that question. We are looking for a Data Scientist to join the squad of four.

What you will do

- Estimate promotion uplift, cannibalisation and halo effects across categories.
- Build price-elasticity models for our everyday prices.
- Work with category managers to plan and evaluate promotion tests in store groups.
- Contribute to our shared Python codebase and our Azure-based platform.

What we look for

- 3+ years of experience as a data scientist, ideally with pricing, marketing or retail data.
- Good grounding in econometrics and causal inference.
- Python and SQL.
- Curiosity about how customers make decisions in a supermarket.

We offer hybrid work with two office days in Valby, pension, health insurance, an employee discount and a friendly team that ships to production every week.

Apply by 28 November 2026. Contact: Squad Lead Jakob Elmgreen, +45 00 00 00 00.`,
    postedDaysAgo: 4,
    score: 0.72,
    reason: 'Her econometrics background and causal-inference work fit uplift and elasticity modelling, but she has no pricing or retail experience and the role is less senior than her current one.',
    matching: ['causal inference', 'econometrics', 'Python', 'SQL'],
    missing: ['pricing', 'price elasticity', 'retail'],
  },
  {
    key: 'klimadata-dataforsker',
    persona: 'mette',
    site: 'jobindex',
    title: 'Dataforsker til klimadata og sæsonprognoser',
    titleEn: 'Data scientist for climate data and seasonal forecasts',
    company: 'Nationalt Institut for Klimadata',
    location: 'Lyngby',
    language: 'da',
    description: `Nationalt Institut for Klimadata (NIK) er en statslig forskningsinstitution, der leverer data og prognoser om vejr og klima til myndigheder, forsyninger og erhvervsliv. Vi søger en dataforsker til vores afdeling for anvendt klimaforskning i Lyngby.

Stillingen

Du kommer til at arbejde med statistiske og maskinlæringsbaserede metoder til sæsonprognoser for temperatur, nedbør og vind. Prognoserne bruges blandt andet af energiselskaber og kommuner til planlægning. Du vil indgå i en gruppe på ni forskere og udviklere og bidrage til både forskningsprojekter og operationelle leverancer.

Dine opgaver vil bl.a. være

- udvikling af statistiske efterbehandlingsmetoder for ensembleprognoser
- validering og formidling af prognosernes usikkerhed
- samarbejde med eksterne brugere om at omsætte prognoser til beslutninger
- publicering i internationale tidsskrifter og deltagelse i EU-finansierede projekter

Kvalifikationer

- ph.d. i statistik, meteorologi, fysik eller tilsvarende
- erfaring med sandsynlighedsbaserede prognoser og validering af dem
- gode programmeringsfærdigheder i Python eller R
- erfaring med store gitterbaserede datasæt (NetCDF, xarray) er en fordel
- gode samarbejds- og formidlingsevner på dansk og engelsk

Løn- og ansættelsesvilkår

Ansættelse sker i henhold til overenskomst mellem Finansministeriet og AC. Stillingen er tidsbegrænset til tre år med mulighed for forlængelse. Der er gode muligheder for faglig udvikling, fleksibel arbejdstid og hjemmearbejde.

Yderligere oplysninger fås hos sektionsleder Hanne Brøndum Vestergaard, tlf. 00 00 00 00.

Ansøgningsfrist: 2. december 2026. Ansøgningen skal indeholde CV, eksamensbeviser og publikationsliste.`,
    postedDaysAgo: 12,
    score: 0.74,
    reason: 'Her PhD and published work on probabilistic forecasting fit the ensemble post-processing well, but she has no meteorology or NetCDF/xarray experience and the post is a fixed-term research position.',
    matching: ['probabilistic forecasting', 'statistics', 'Python', 'R'],
    missing: ['NetCDF', 'xarray', 'meteorology'],
  },
  {
    key: 'region-midtkyst-patientflow',
    persona: 'mette',
    site: 'jobbank',
    title: 'Data Scientist til prognoser for patientflow',
    titleEn: 'Data Scientist for patient flow forecasts',
    company: 'Region Midtkyst, Hospitalsenheden Øst',
    location: 'Copenhagen',
    language: 'da',
    description: `Hvor mange patienter kommer ind på akutmodtagelsen i morgen? Og hvor mange senge skal vi have klar på medicinsk afdeling i næste uge? Vi søger en data scientist, der kan hjælpe os med at svare bedre på de spørgsmål.

Om enheden

Hospitalsenheden Øst er et af regionens største hospitaler med 5.200 ansatte. Vores afdeling for Data og Analyse består af 14 medarbejdere, som leverer ledelsesinformation, analyser og prognoser til hospitalets ledelse og kliniske afdelinger.

Opgaverne

- Udvikle og drive prognoser for indlæggelser, belægning og ventetider på afdelingsniveau.
- Samarbejde tæt med klinikere og planlæggere om at bruge prognoserne i den daglige drift.
- Bidrage til at etablere bedre praksis for modeludvikling, versionering og drift i afdelingen.
- Formidle resultater klart til ledelsen.

Vi forventer, at du

- har en kandidatgrad i statistik, matematik, datalogi eller lignende
- har erfaring med tidsrækkeprognoser og Python eller R
- har kendskab til SQL og gerne til Power BI
- kan lide at arbejde tæt sammen med mennesker med en anden faglighed end din egen

Erfaring fra sundhedsvæsenet er en fordel, men ikke et krav.

Vi tilbyder

Et meningsfuldt job, hvor dine analyser har direkte betydning for patienterne. Løn efter overenskomst, 37 timers arbejdsuge, mulighed for hjemmearbejde én dag om ugen og gode muligheder for efteruddannelse.

Kontakt afdelingschef Torben Lykke Rasmussen på tlf. 00 00 00 00 for yderligere oplysninger. Ansøgningsfrist den 27. november 2026. Samtaler forventes afholdt i uge 49.`,
    postedDaysAgo: 7,
    score: 0.77,
    reason: 'Her forecasting, Power BI and MLOps experience covers the admissions and occupancy forecasts and the wish for better model practice. No healthcare background, and the role is narrower than her current one.',
    matching: ['time-series forecasting', 'Python', 'SQL', 'Power BI', 'MLOps'],
    missing: ['healthcare data'],
  },
  {
    key: 'lindegaard-bio-clinical-analytics',
    persona: 'mette',
    site: 'greenhouse',
    title: 'Senior Data Scientist, Clinical Analytics',
    company: 'Lindegaard Bio',
    location: 'Lyngby',
    language: 'en',
    description: `Lindegaard Bio develops antibody therapies for autoimmune diseases. With two candidates in Phase II trials and a growing pipeline, we are building a Clinical Analytics group that brings modern data science to how we design and run our trials.

The position

You will join a new group of four data scientists and two statistical programmers, working closely with Clinical Operations and Biostatistics. Your focus will be on predictive models for patient recruitment and site performance, and on the analysis of real-world data to support trial design.

Key responsibilities

- Forecast patient enrolment across 120 trial sites and flag sites at risk of missing targets.
- Build models on real-world data to estimate eligible patient populations.
- Apply causal methods to observational data in close collaboration with biostatisticians.
- Help build a validated, GxP-compliant analytics environment.

Qualifications

- MSc or PhD in statistics, epidemiology, data science or a related field.
- 5+ years of experience in data science, ideally in pharma, biotech or healthcare.
- Strong Python or R and SQL; experience with forecasting and causal inference.
- Familiarity with clinical trial data standards (CDISC) and GxP is a strong advantage.

We offer

An ambitious science-driven company, a modern site at Lyngby Biotech Park, a competitive package with bonus and pension, and the chance to shape a new function from the start.

Please apply by 5 December 2026. For questions, contact Director of Clinical Analytics Nina Sejer at +45 00 00 00 00.`,
    postedDaysAgo: 14,
    score: 0.68,
    reason: 'Her forecasting and causal-inference skills transfer to enrolment forecasts and observational studies, but she has no pharma, CDISC or GxP experience, which the ad weighs heavily.',
    matching: ['forecasting', 'causal inference', 'Python', 'R', 'SQL'],
    missing: ['GxP', 'CDISC', 'clinical trials', 'epidemiology'],
  },
  {
    key: 'egeskov-kommune-prognoser',
    persona: 'mette',
    site: 'jobindex',
    title: 'Datafaglig konsulent med fokus på prognoser og befolkningsdata',
    titleEn: 'Data consultant focusing on forecasts and population data',
    company: 'Egeskov Kommune',
    location: 'Odense',
    language: 'da',
    description: `Hvor mange børn skal vi have plads til i vores dagtilbud om fem år? Og hvor mange ældre får brug for hjemmepleje? Egeskov Kommune søger en datafaglig konsulent, der vil være med til at give vores politikere og ledere et bedre grundlag for at planlægge velfærden.

Om os

Du bliver en del af Økonomi og Analyse, som består af 18 engagerede medarbejdere. Vi har ansvaret for kommunens budget, analyser og befolkningsprognoser og arbejder tæt sammen med fagområderne.

Dine opgaver

- Udarbejde og videreudvikle kommunens befolkningsprognose og kapacitetsprognoser for skoler, dagtilbud og ældreområdet.
- Gennemføre analyser af effekten af kommunale indsatser.
- Udvikle dashboards i Power BI til ledere og politikere.
- Bidrage til at modernisere vores datagrundlag og arbejdsgange.

Din profil

Du har en relevant akademisk uddannelse, fx inden for statistik, økonomi eller samfundsvidenskab, og erfaring med prognoser og dataanalyse. Du arbejder sikkert i SQL og Power BI, og det er en fordel, hvis du kan programmere i R eller Python. Du er god til at formidle tal, så de giver mening for andre.

Vi tilbyder

En stilling med stor indflydelse og synlighed, gode kolleger, fleksibel arbejdstid og mulighed for hjemmearbejde. Løn og ansættelse efter gældende overenskomst.

Vil du vide mere, er du velkommen til at kontakte analysechef Birgitte Ravn Søndergaard på tlf. 00 00 00 00.

Ansøgningsfrist: 26. november 2026. Vi forventer at holde samtaler den 3. december.`,
    postedDaysAgo: 10,
    score: 0.7,
    reason: 'She has the forecasting, causal-inference and Power BI skills asked for, but the population and capacity forecasts are simpler than her current work and she has no public-sector experience.',
    matching: ['forecasting', 'causal inference', 'Power BI', 'SQL', 'Python'],
    missing: ['demographic forecasting', 'public sector'],
  },
  {
    key: 'gridwise-ml-engineer-remote',
    persona: 'mette',
    site: 'lever',
    title: 'Senior ML Engineer, Forecasting Platform',
    company: 'Gridwise Labs',
    location: 'Remote (EU)',
    language: 'en',
    description: `Gridwise Labs builds software that lets grid operators and energy retailers forecast load and renewable production without building their own data science team. Our platform serves 40 customers in nine countries and produces 30 million forecasts a day.

We are a remote-first company of 60 people across Europe, and we are looking for a Senior ML Engineer to join our Forecasting Platform team.

What you'll do

- Design and scale the pipelines that train and serve thousands of customer-specific forecasting models.
- Improve our automated model selection and backtesting framework.
- Own reliability: monitoring, alerting and the quality of forecasts we deliver at 6 am every day.
- Collaborate with our research team when their new methods move to production.

What you need

- 5+ years building ML systems in production, at least partly with time-series data.
- Strong Python and solid software engineering practices.
- Experience with Kubernetes, workflow orchestration and model registries.
- Experience with AWS (our platform runs there).
- Comfortable working asynchronously across time zones.

What we offer

Fully remote within the EU, an annual team gathering, a competitive salary benchmarked to your country, stock options, a home-office budget and 30 days of holiday.

Apply via our careers page. We aim to complete the process within three weeks.`,
    postedDaysAgo: 15,
    score: 0.78,
    reason: 'Her forecasting background and production MLOps setup at Vindstrøm fit the platform, but the role is engineering-heavy, runs on AWS rather than her Azure, and serves thousands of models instead of a few.',
    matching: ['time-series forecasting', 'MLOps', 'Kubernetes', 'Airflow', 'Python'],
    missing: ['AWS', 'large-scale model serving'],
  },
  {
    key: 'kystbanken-quant-analyst',
    persona: 'mette',
    site: 'jobbank',
    title: 'Quantitative Analyst, Market Risk',
    company: 'Kystbanken A/S',
    location: 'Copenhagen',
    language: 'en',
    description: `Kystbanken is a Danish commercial bank with 1,100 employees serving private customers and small and medium-sized businesses. Our Market Risk department is looking for a Quantitative Analyst to strengthen our modelling of interest-rate and credit-spread risk.

Your role

- Develop and validate market-risk models (VaR, expected shortfall, stress testing).
- Model prepayment behaviour on Danish mortgage bonds.
- Contribute to regulatory reporting and the dialogue with the Danish FSA.
- Automate the department's analyses in Python.

Your profile

- MSc or PhD in mathematics, statistics, physics or mathematical economics.
- 3+ years of experience with quantitative modelling, preferably in risk or trading.
- Strong programming skills in Python; C++ or a similar language is a plus.
- Knowledge of fixed income and derivatives pricing.
- Fluent in English; Danish is an advantage.

We offer a professional environment, a good work-life balance, pension, health insurance and flexible working hours. Our office is centrally located at Kongens Nytorv.

The team

Market Risk is a team of nine quants and risk managers who sit next to the treasury and trading desks. We value clear documentation, peer review of every model and a calm working pace, also around quarter-end.

Application deadline: 30 November 2026. Contact Head of Market Risk Jens Kragelund, tel. +45 00 00 00 00.`,
    postedDaysAgo: 18,
    score: 0.66,
    reason: 'Her mathematics-economics degree, PhD and price-spread modelling give a quantitative base, but the role needs fixed income, derivatives pricing and regulatory risk models she has not worked with.',
    matching: ['statistics', 'Python', 'quantitative modelling'],
    missing: ['fixed income', 'derivatives pricing', 'C++', 'regulatory reporting'],
  },
  {
    key: 'engvang-supply-chain-ds',
    persona: 'mette',
    site: 'jobbank',
    title: 'Senior Data Scientist, Supply Chain',
    company: 'Mejeriselskabet Engvang',
    location: 'Aarhus',
    language: 'en',
    description: `Mejeriselskabet Engvang is a farmer-owned dairy cooperative with 3,800 employees and products sold in 50 markets. Milk is a living product: it arrives every day whether we need it or not, and it has to go somewhere within hours. Planning that flow is a forecasting and optimisation problem like few others.

Our Supply Chain Analytics team in Aarhus (seven people) is looking for a Senior Data Scientist.

Responsibilities

- Forecast milk intake and product demand across our dairies and markets.
- Build optimisation models for allocating milk to products and production sites.
- Work with planners to embed models in our sales and operations planning process.
- Help the team move models from scripts to a maintained platform on Azure.

Requirements

- 5+ years of experience with forecasting and/or optimisation in supply chain or manufacturing.
- Strong Python; experience with SQL and an optimisation library (Pyomo, OR-Tools or similar).
- Ability to work with planners and production managers on the floor.
- Fluent English; Danish is an advantage.

We offer a permanent position, pension, canteen, flexible working hours and a good dose of cheese.

Deadline: 4 December 2026. Contact: Head of Supply Chain Analytics Mikkel Aagaard, +45 00 00 00 00.`,
    postedDaysAgo: 13,
    score: 0.79,
    reason: 'Her logistics demand forecasting and OR-Tools optimisation at Nordhavn Logistik and her Azure MLOps work match well; dairy and S&OP are new, and the job is in Aarhus.',
    matching: ['demand forecasting', 'optimisation', 'Pyomo', 'OR-Tools', 'Python', 'Azure'],
    missing: ['S&OP'],
  },

  // ---------------------------------------------------------------- mette: weak
  {
    key: 'skovlund-data-engineer-azure',
    persona: 'mette',
    site: 'jobbank',
    title: 'Data Engineer (Azure)',
    company: 'Skovlund Consulting',
    location: 'Copenhagen',
    language: 'en',
    description: `Skovlund Consulting is a 70-person consultancy helping Danish companies build modern data platforms. We are looking for a Data Engineer who wants variety: you will work on two or three client projects a year, from public organisations to listed companies.

Your tasks

- Design and build data platforms on Azure: Data Factory, Synapse, Databricks and Fabric.
- Build robust ingestion pipelines and data models.
- Set up CI/CD and infrastructure as code with Terraform or Bicep.
- Advise clients on architecture and governance.

Your profile

- 3+ years as a data engineer, preferably as a consultant.
- Strong SQL and Python or Scala.
- Hands-on experience with Azure data services and Databricks.
- Microsoft certifications (DP-203 or similar) are a plus.
- You enjoy client contact and speak Danish and English.

We offer a competitive salary, bonus, pension, a certification budget and a social, flat organisation in central Copenhagen. Most projects are within the Greater Copenhagen area, and you will always work in teams of at least two consultants from Skovlund, never alone at a client.

Our recruitment process has two interviews and a short case about a data platform design. We do not use personality tests.

Apply by 30 November 2026. Contact Partner Louise Hvid, +45 00 00 00 00.`,
    postedDaysAgo: 16,
    score: 0.58,
    reason: 'She knows Azure, SQL and dbt-style data modelling, but this is a data engineering consultancy role with Data Factory, Synapse and Terraform, far from her forecasting and modelling focus.',
    matching: ['Azure', 'SQL', 'Python', 'dbt'],
    missing: ['Azure Data Factory', 'Synapse', 'Terraform', 'consulting'],
  },
  {
    key: 'ostjysk-bolig-bi-udvikler',
    persona: 'mette',
    site: 'jobindex',
    title: 'BI-udvikler til vores dataplatform',
    titleEn: 'BI developer for our data platform',
    company: 'Østjysk Bolig',
    location: 'Aarhus',
    language: 'da',
    description: `Østjysk Bolig administrerer 14.000 almene boliger i Aarhus og omegn. Vi er i gang med at samle vores data i en ny platform, og vi søger en BI-udvikler, der kan hjælpe os med at få mest muligt ud af den.

Dine opgaver

- Udvikle og vedligeholde rapporter og dashboards i Power BI til ledelse, driftsafdelinger og boligorganisationer.
- Bygge datamodeller i vores data warehouse på Azure SQL.
- Hjælpe kolleger med at bruge data i hverdagen.
- Deltage i arbejdet med datakvalitet og dokumentation.

Vi forventer

- erfaring med Power BI, DAX og datamodellering
- god forståelse for SQL
- interesse for at forstå forretningen og møde brugerne
- gode samarbejdsevner og et godt humør

Vi tilbyder

Et job i en organisation med et socialt formål, 37 timer om ugen med fleksible arbejdstider, frokostordning, personalearrangementer og pension. Kontoret ligger i Aarhus N med gode parkeringsforhold.

Om teamet

Du bliver en del af et lille datateam på tre personer, som sidder i IT-afdelingen sammen med syv kolleger. Vi arbejder tæt med økonomi, udlejning og driften ude i afdelingerne, og vi holder af at gøre tingene enkle og brugbare.

Kontakt IT-chef Lars Mørup på 00 00 00 00 for mere information. Ansøgningsfrist den 22. november 2026.`,
    postedDaysAgo: 19,
    score: 0.45,
    reason: 'She has Power BI and SQL from Nordhavn Logistik, but this is a reporting role with DAX and no modelling or forecasting, well below her level.',
    matching: ['Power BI', 'SQL', 'data modelling'],
    missing: ['DAX', 'Azure SQL'],
  },
  {
    key: 'bolgen-head-of-data-ai',
    persona: 'mette',
    site: 'thehub',
    title: 'Head of Data & AI',
    company: 'Bølgen Media',
    location: 'Copenhagen',
    language: 'en',
    description: `Bølgen Media publishes three digital news sites and a podcast network with 1.4 million weekly users in Denmark. We are looking for a Head of Data & AI to lead our data organisation through its next chapter.

The role

You will lead a department of 16 people across data engineering, analytics and data science, reporting to the CTO. You will set the data strategy, own the budget and drive our work on recommendation, subscription analytics and responsible use of generative AI in the newsroom.

What we look for

- Several years of experience leading data teams of 10+ people, including managers.
- A track record of setting strategy and delivering it with budget responsibility.
- Experience with recommender systems, subscription or media analytics.
- Strong understanding of data governance, GDPR and AI ethics.
- Excellent communication in Danish and English, including with editors and the executive board.

We offer a central role in a company that matters for Danish public debate, a competitive package, pension and a vibrant office at Islands Brygge.

Apply by 20 November 2026. Contact CTO Signe Ahlefeldt via The Hub.`,
    postedDaysAgo: 21,
    score: 0.55,
    reason: 'She mentors three data scientists but has not led a department of 16 or managed a budget, and recommender systems and media analytics are outside her experience.',
    matching: ['data science', 'stakeholder management', 'mentoring'],
    missing: ['people management', 'budget responsibility', 'recommender systems', 'media analytics'],
  },
  {
    key: 'agrisense-computer-vision',
    persona: 'mette',
    site: 'thehub',
    title: 'Computer Vision Engineer',
    company: 'Agrisense Robotics',
    location: 'Odense',
    language: 'en',
    description: `Agrisense Robotics builds autonomous field robots that remove weeds without chemicals. Our robots are driving in fields in Denmark, Germany and the Netherlands, and our vision system decides 20 times a second what is a crop and what is a weed.

We are 35 people in Odense, and we are looking for a Computer Vision Engineer to join our perception team of five.

You will

- Train and improve deep-learning models for plant detection and segmentation.
- Optimise models for real-time inference on NVIDIA Jetson hardware.
- Build the data pipeline from field images to labelled training sets.
- Spend time in the field testing the robot (rubber boots provided).

You have

- 3+ years of experience with computer vision and deep learning (PyTorch).
- Experience with model optimisation for edge devices (TensorRT, ONNX).
- Solid Python; C++ is a plus.
- A hands-on mindset.

Our robots will drive on 2,000 hectares next season, and every percentage point of better detection means less crop damage and happier farmers. You will see your models in the field within weeks of training them.

We offer warrants, pension, flexible hours, lunch, and a workshop full of robots. We are a team of engineers, agronomists and farmers' children who like to get our hands dirty, and we celebrate every new field with cake.

Apply via The Hub. Contact: Head of Perception Kasper Fenger.`,
    postedDaysAgo: 20,
    score: 0.34,
    reason: 'Apart from Python and some PyTorch, the role needs computer vision, edge deployment and C++, none of which are on her CV.',
    matching: ['Python', 'PyTorch', 'machine learning'],
    missing: ['computer vision', 'TensorRT', 'edge deployment', 'C++'],
  },
  {
    key: 'loopa-product-analyst',
    persona: 'mette',
    site: 'thehub',
    title: 'Product Analyst',
    company: 'Loopa',
    location: 'Copenhagen',
    language: 'en',
    description: `Loopa is a second-hand marketplace app for children's clothes with 600,000 users in the Nordics. We are a team of 40 and we want every product decision to be informed by data.

As our Product Analyst you will

- Define and track the metrics that matter for each product squad.
- Design and analyse A/B tests on new features.
- Dig into user behaviour with SQL and our product analytics tool (Amplitude).
- Present insights at our fortnightly product reviews.

You bring

- 2+ years in product or growth analytics.
- Strong SQL and experience with Amplitude, Mixpanel or similar.
- Solid understanding of experimentation.
- Python or R is a plus.

About us

Loopa was founded by two parents who were tired of throwing away clothes their children had outgrown after three months. Today, more than two million items have found a second home through the app, and we are profitable in Denmark and Sweden. Our product squads are small (four to six people) and own their area end to end, from the idea to the experiment and the rollout.

We offer a fun, mission-driven team, warrants, pension and a dog-friendly office in Nørrebro.

Apply via The Hub with your CV and a short note about a test you ran that surprised you.`,
    postedDaysAgo: 22,
    score: 0.61,
    reason: 'Her A/B testing and SQL experience fit, but this is a junior product analytics role with Amplitude, far from her forecasting and modelling seniority.',
    matching: ['A/B testing', 'SQL', 'Python', 'experimentation'],
    missing: ['Amplitude', 'product analytics'],
  },
  {
    key: 'kvikbyg-analytics-engineer',
    persona: 'mette',
    site: 'jobindex',
    title: 'Analytics Engineer (dbt)',
    company: 'Kvikbyg',
    location: 'Aarhus',
    language: 'en',
    description: `Kvikbyg sells building materials online to craftsmen and DIY customers across Denmark. Our data team of six is looking for an Analytics Engineer to own the layer between raw data and the dashboards our business runs on.

Your responsibilities

- Build and maintain our dbt models in Snowflake.
- Define metrics with the business and keep them consistent.
- Improve data quality checks, documentation and testing.
- Support analysts and data scientists with clean, reliable tables.

Your background

- 2+ years with dbt and a cloud data warehouse.
- Excellent SQL.
- Some Python.
- An eye for data quality.

About the team

The data team sits between e-commerce, purchasing and finance. We moved from a tangle of spreadsheets to Snowflake and dbt last year, and we now have 300 models and a growing appetite for more. You will be the person who keeps that layer clean, tested and understandable, and who helps our two data scientists get the features they need for their demand and pricing models.

We offer a permanent position, pension, flexible hours, lunch scheme and a casual office by the river in Aarhus.

Apply by 29 November 2026. Contact Head of Data Anne-Sofie Kjeldsen, +45 00 00 00 00.`,
    postedDaysAgo: 17,
    score: 0.63,
    reason: 'She built the Snowflake and dbt data model at Nordhavn Logistik, but this role is pure analytics engineering with no modelling, below her level and focus.',
    matching: ['dbt', 'Snowflake', 'SQL', 'Python'],
    missing: ['data quality testing'],
  },

  // ---------------------------------------------------------------- mette: dropped before scoring
  {
    key: 'havnefront-ds-internship',
    persona: 'mette',
    site: 'thehub',
    title: 'Data Science Internship (Spring 2027)',
    company: 'Havnefront Analytics',
    location: 'Copenhagen',
    language: 'en',
    description: `Havnefront Analytics builds forecasting tools for ports and terminals. We are looking for a Data Science intern for the spring semester 2027 (February to June, 20 hours a week).

As an intern you will

- Help our data scientists clean and explore vessel arrival data.
- Build a first prototype of a berth-occupancy forecast.
- Present your results to the team at the end of the semester.

You are

- A student in statistics, data science, computer science or a related field.
- Comfortable with Python and pandas.
- Curious and not afraid to ask questions.

About us

We are a team of twelve, most of us data scientists and software engineers, working from an old warehouse at the harbour. Our customers are port authorities and terminal operators in Denmark, Norway and Germany who use our tools to plan berths, cranes and staff.

We offer a monthly salary of DKK 12,000, a mentor, lunch, and the chance to write your thesis with us afterwards.

Apply via The Hub by 15 December 2026 with your CV, your grade transcript and a few lines about a dataset you enjoyed working with. We hold interviews in early January.`,
    postedDaysAgo: 5,
    score: null,
    reason: 'Not scored: the title contains "internship", one of the profile\'s excluded keywords.',
    matching: [],
    missing: [],
  },

  // ---------------------------------------------------------------- mette: fresh (a run finds these)
  {
    key: 'havtorn-lead-ds',
    persona: 'mette',
    site: 'jobindex',
    title: 'Lead Data Scientist',
    company: 'Havtorn Energi',
    location: 'Copenhagen (hybrid)',
    language: 'en',
    description: `Havtorn Energi develops, owns and operates offshore wind and battery storage in Denmark and the Baltic Sea. With 1.8 GW in operation and twice that under construction, we are building a data science team that will decide how our assets earn money in the power markets.

The role

As Lead Data Scientist you will build the team's methods and its first people. You will report to the Head of Energy Management and work closely with our traders and asset managers.

Responsibilities

- Own production and price forecasting for our offshore parks and batteries.
- Build models for battery dispatch and balancing-market bidding together with our optimisation engineer.
- Set up the team's MLOps foundation on Azure.
- Recruit and mentor two to three data scientists during 2027.

Your profile

- 7+ years of data science experience, much of it in energy or commodity trading.
- Deep knowledge of time-series and probabilistic forecasting.
- Proven experience putting models into production.
- Experience mentoring or leading data scientists.
- Fluent English; Danish is a plus.

We offer a key role in a growing renewable company, a competitive salary with bonus, 12% pension, health insurance and hybrid work from our office in Nordhavn.

Apply by 10 December 2026. Contact Head of Energy Management Tue Holmsgaard, +45 00 00 00 00.`,
    postedDaysAgo: 0,
    score: 0.89,
    reason: 'Her production and price-spread forecasting for a power-trading desk, the MLOps setup she built on Azure and her mentoring at Vindstrøm match the role closely; battery dispatch optimisation is new.',
    matching: ['probabilistic forecasting', 'power trading', 'MLOps', 'Azure', 'mentoring'],
    missing: ['battery dispatch optimisation'],
    fresh: true,
  },
  {
    key: 'varmevaerk-ost-varmeprognoser',
    persona: 'mette',
    site: 'jobindex',
    title: 'Data Scientist til varmeprognoser',
    titleEn: 'Data Scientist for heat demand forecasts',
    company: 'Varmeværk Øst I/S',
    location: 'Copenhagen',
    language: 'da',
    description: `Varmeværk Øst leverer fjernvarme til 160.000 husstande i hovedstadsområdet. Når vi kan forudsige varmebehovet præcist, kan vi bruge mere overskudsvarme og grøn el og mindre biomasse. Derfor søger vi en data scientist til vores driftsoptimering.

Opgaverne

- Videreudvikle vores prognoser for varmebehov fra time til uge på baggrund af vejrdata og forbrugsdata.
- Udvikle modeller for optimal drift af varmepumper, elkedler og varmelagre.
- Sætte modeller i drift og overvåge dem sammen med IT.
- Samarbejde med driftsingeniører og kontrolrummet.

Din profil

- Kandidat- eller ph.d.-uddannelse inden for statistik, matematik, ingeniørvidenskab eller lignende.
- Erfaring med tidsrækkeprognoser og maskinlæring i Python.
- Gerne kendskab til optimering og energisystemer.
- Du taler og skriver dansk.

Vi tilbyder

En samfundsvigtig opgave i den grønne omstilling, gode kolleger, fleksible arbejdstider, pension og kantine. Arbejdsstedet er i Valby.

Om afdelingen

Driftsoptimering er seks ingeniører og analytikere, der sidder tæt på kontrolrummet. Vi har i år sat to store varmepumper og et nyt varmelager i drift, og det gør prognoserne vigtigere end nogensinde: jo bedre vi kender behovet, jo mere kan vi køre på strøm, når den er billig og grøn.

Kontakt driftschef Martin Skov Pedersen på 00 00 00 00. Ansøgningsfrist: 8. december 2026.`,
    postedDaysAgo: 1,
    score: 0.76,
    reason: 'Her weather-driven forecasting and optimisation experience fits heat-demand forecasts and plant scheduling, though district heating is a new domain and the role is less senior.',
    matching: ['time-series forecasting', 'optimisation', 'Python', 'MLOps'],
    missing: ['district heating'],
    fresh: true,
  },
  {
    key: 'nordlys-retail-marketing-analyst',
    persona: 'mette',
    site: 'jobindex',
    title: 'Marketing Data Analyst',
    company: 'Nordlys Retail',
    location: 'Copenhagen',
    language: 'en',
    description: `Nordlys Retail runs 60 fashion and home stores and a webshop. Our marketing team is looking for a Data Analyst who can tell us which campaigns work and where to spend the next krone.

You will

- Report on campaign performance across paid social, search, e-mail and stores.
- Build and maintain marketing dashboards in Looker Studio.
- Support media-mix modelling with our external agency.
- Run simple tests on e-mail and landing pages.

You have

- 2+ years in marketing or e-commerce analytics.
- Good SQL and Google Analytics 4.
- Experience with Looker Studio or similar.
- Danish and English.

About the team

You will join a marketing team of 14 people, of which two work with data and marketing technology. You will work closely with our CRM manager and our external media agency, and present results at the monthly marketing meeting. Our customers are loyal, and our customer club has 280,000 members, which gives us good data to work with.

We offer a creative environment, 30% staff discount, pension, lunch scheme and an office in Indre By.

Apply by 5 December 2026 with your CV and a few words about a campaign analysis you are proud of.`,
    postedDaysAgo: 0,
    score: 0.48,
    reason: 'Her SQL and testing experience apply, but the role is marketing reporting with Google Analytics and Looker Studio, a step down from her forecasting work.',
    matching: ['SQL', 'A/B testing', 'statistics'],
    missing: ['Google Analytics 4', 'Looker Studio', 'marketing analytics'],
    fresh: true,
  },

  // ---------------------------------------------------------------- lea
  {
    key: 'ferrovia-controleur-industriel',
    persona: 'lea',
    site: 'francetravail',
    title: 'Contrôleur de gestion industriel H/F',
    titleEn: 'Industrial management controller',
    company: 'Ferrovia Composants',
    location: 'Lyon',
    language: 'fr',
    description: `Ferrovia Composants conçoit et fabrique des systèmes de freinage et des pièces de structure pour le matériel ferroviaire. Nous employons 650 personnes sur trois sites en Auvergne-Rhône-Alpes et réalisons 140 M€ de chiffre d'affaires, dont 60 % à l'export.

Dans le cadre d'une création de poste, nous recherchons un Contrôleur de gestion industriel H/F, rattaché au Directeur administratif et financier et basé à notre siège de Lyon Gerland.

Vos missions

- Piloter le contrôle de gestion de nos deux usines de la région lyonnaise.
- Élaborer le budget annuel et les reprévisions avec les directeurs de site.
- Mettre à jour les coûts standards et analyser les écarts de production (matières, main-d'œuvre, frais).
- Animer les revues de performance mensuelles avec les équipes opérationnelles.
- Participer à la valorisation des stocks et aux clôtures mensuelles.
- Contribuer au déploiement de Power BI pour le reporting industriel.

Votre profil

De formation Bac+5 en contrôle de gestion ou école de commerce, vous justifiez d'au moins cinq ans d'expérience en contrôle de gestion industriel. Vous maîtrisez SAP (module CO) et Excel, et une première expérience de Power BI serait appréciée. Vous aimez le terrain et savez construire une relation de confiance avec les équipes de production. Un anglais professionnel est nécessaire pour échanger avec notre maison mère.

Ce que nous offrons

- CDI, statut cadre, forfait jours.
- Rémunération : 48 à 55 k€ bruts annuels selon expérience, plus intéressement et participation.
- Télétravail deux jours par semaine.
- Mutuelle et prévoyance prises en charge à 70 %, restaurant d'entreprise.

Pour postuler, envoyez votre CV et une lettre de motivation via France Travail en indiquant la référence FC-CDG-2611. Contact : Claire Vasseur, responsable RH, 04 00 00 00 00.`,
    postedDaysAgo: 3,
    score: 0.88,
    reason: 'Son poste actuel chez Rhodanis Mécanique (deux usines, budget, coûts standards, reporting Power BI) correspond presque point par point à la fiche ; elle maîtrise aussi SAP CO.',
    matching: ['contrôle de gestion industriel', 'coûts standards', 'budget et reprévisions', 'SAP CO', 'Power BI'],
    missing: [],
  },
  {
    key: 'laiterie-monts-controleur-usine',
    persona: 'lea',
    site: 'francetravail',
    title: "Contrôleur de gestion d'usine (H/F)",
    titleEn: 'Plant controller',
    company: 'Laiterie des Monts du Lyonnais',
    location: 'Villefranche-sur-Saône',
    language: 'fr',
    description: `La Laiterie des Monts du Lyonnais, coopérative laitière de 320 salariés, transforme chaque année 180 millions de litres de lait en fromages, yaourts et desserts vendus en grande distribution.

Nous recrutons un Contrôleur de gestion d'usine H/F pour notre site de Villefranche-sur-Saône.

Missions principales

- Suivre les coûts de production et les rendements matière par ligne.
- Construire le budget de l'usine et suivre les reprévisions.
- Analyser les écarts et proposer des plans d'action avec le directeur d'usine.
- Réaliser les inventaires et valoriser les stocks.
- Assurer la clôture mensuelle avec la comptabilité.

Profil recherché

- Bac+5 en contrôle de gestion.
- Trois ans d'expérience minimum en environnement industriel, idéalement agroalimentaire.
- Maîtrise d'Excel ; la connaissance d'un ERP agroalimentaire (type M3) est un plus.
- Rigueur, curiosité et goût pour le terrain.

Vous travaillerez en lien étroit avec le directeur d'usine, les responsables de production et le service qualité, et serez rattaché(e) au directeur administratif et financier de la coopérative.

Nous proposons un CDI, une rémunération de 42 à 48 k€ selon profil, un treizième mois, l'intéressement et des produits de la coopérative à tarif préférentiel.

Candidature via France Travail, référence LML-2026-14. Contact : Sébastien Ollier, directeur administratif, 04 00 00 00 00.`,
    postedDaysAgo: 8,
    score: 0.79,
    reason: "Elle a l'expérience des coûts de production, budgets et inventaires en usine, mais pas de l'agroalimentaire ni de l'ERP M3 ; le poste est aussi moins large que son poste actuel.",
    matching: ['coûts de revient', 'budget et reprévisions', 'analyse des écarts', 'clôtures mensuelles'],
    missing: ['agroalimentaire', 'M3'],
  },
  {
    key: 'helianthe-responsable-cdg',
    persona: 'lea',
    site: 'francetravail',
    title: 'Responsable contrôle de gestion H/F',
    titleEn: 'Head of management control',
    company: 'Groupe Hélianthe Santé',
    location: 'Lyon',
    language: 'fr',
    description: `Le Groupe Hélianthe Santé exploite douze cliniques privées en Auvergne-Rhône-Alpes et emploie 2 800 collaborateurs. Pour accompagner notre croissance, nous recherchons notre Responsable contrôle de gestion H/F.

Vos missions

- Encadrer une équipe de trois contrôleurs de gestion.
- Piloter le processus budgétaire du groupe et les reprévisions.
- Produire le reporting mensuel à destination du comité exécutif et des actionnaires.
- Analyser la rentabilité par établissement et par activité médicale.
- Accompagner les projets d'acquisition (business plans, intégration).

Votre profil

Diplômé(e) d'un Bac+5 en finance, vous avez au moins huit ans d'expérience en contrôle de gestion, dont une première expérience de management. Une connaissance du secteur de la santé est un atout. Vous maîtrisez les outils de reporting (Power BI) et êtes à l'aise avec les instances de direction.

Le poste est rattaché au Directeur financier du groupe. Vous travaillerez en lien avec les directeurs d'établissement, les équipes médicales et le service comptable, et serez l'interlocuteur des commissaires aux comptes pour le volet contrôle de gestion.

Poste en CDI basé à Lyon 7e, rémunération de 65 à 75 k€ selon expérience, télétravail partiel.

Postulez via France Travail. Contact : Delphine Martel, DRH, 04 00 00 00 00.`,
    postedDaysAgo: 12,
    score: 0.68,
    reason: "Elle maîtrise le budget, le reporting Power BI et l'analyse de rentabilité, mais n'a ni les huit ans d'expérience ni le management d'équipe demandés, et ne connaît pas le secteur de la santé.",
    matching: ['budget et reprévisions', 'Power BI', 'business partnering'],
    missing: ['management', 'secteur de la santé', 'acquisitions'],
  },
  {
    key: 'saone-capital-analyste-fpa',
    persona: 'lea',
    site: 'francetravail',
    title: 'Analyste financier FP&A H/F',
    titleEn: 'FP&A financial analyst',
    company: 'Saône Logiciels',
    location: 'Lyon',
    language: 'fr',
    description: `Saône Logiciels édite une solution SaaS de gestion pour les cabinets d'architectes. Avec 9 000 clients et une croissance de 35 % par an, nous renforçons notre équipe finance.

Missions

- Suivre les indicateurs SaaS (ARR, churn, coût d'acquisition client).
- Participer au budget et au plan à cinq ans.
- Préparer les reportings pour le conseil d'administration et les investisseurs.
- Automatiser les analyses dans notre outil de planification.

Profil

- Bac+5 école de commerce ou finance.
- Deux à quatre ans d'expérience en FP&A, audit ou contrôle de gestion, idéalement dans le logiciel.
- Excellente maîtrise d'Excel ; SQL apprécié.
- Anglais courant.

L'équipe

Vous rejoindrez une équipe finance de six personnes, rattachée au directeur financier. Nous préparons une nouvelle levée de fonds en 2027 et vous serez au cœur de la préparation des données pour les investisseurs. Le poste offre une vraie exposition à la direction et des perspectives d'évolution rapides.

CDI à Lyon Part-Dieu, 45 à 52 k€, BSPCE, carte titre-restaurant, télétravail flexible.

Candidature via France Travail, référence SL-FPA-07. Le processus comprend un entretien avec le directeur financier, un cas pratique sur Excel et une rencontre avec l'équipe.`,
    postedDaysAgo: 15,
    score: 0.55,
    reason: "Elle a le budget, Excel avancé et des notions de SQL, mais son expérience est industrielle et le poste porte sur les indicateurs SaaS et le reporting aux investisseurs.",
    matching: ['budget et reprévisions', 'Excel avancé', 'SQL'],
    missing: ['indicateurs SaaS', 'reporting investisseurs'],
  },

  // ---------------------------------------------------------------- bence
  {
    key: 'tisza-pay-senior-go',
    persona: 'bence',
    site: 'greenhouse',
    title: 'Senior Backend Engineer (Go)',
    company: 'Tisza Pay',
    location: 'Budapest',
    language: 'en',
    description: `Tisza Pay is a payment gateway for merchants in Central and Eastern Europe, processing EUR 4 billion a year for 12,000 merchants. Our engineering team of 70 in Budapest builds everything in-house, from the card authorisation path to the merchant dashboard.

We are looking for a Senior Backend Engineer to join the Core Payments team.

What you will do

- Build and operate services in Go that authorise, capture and settle card payments.
- Design APIs and event flows that stay correct under retries, timeouts and partial failures.
- Improve latency and throughput of our PostgreSQL-backed services.
- Share on-call duties and lead post-incident reviews.
- Mentor engineers and take part in architecture decisions.

What you bring

- 5+ years of backend engineering, at least 2 with Go.
- Strong PostgreSQL knowledge, including query tuning.
- Experience with Kafka or another event streaming platform.
- A track record of running services in production on Kubernetes.
- Payments or fintech experience is a big plus.

What we offer

Competitive salary in EUR, yearly bonus, private health insurance, a SZÉP card, hybrid work with two office days in our office by the Danube, and a yearly conference budget.

Apply through our careers page. Questions: Engineering Manager Dóra Szilágyi, dora.szilagyi@tiszapay.example.`,
    postedDaysAgo: 4,
    score: 0.87,
    reason: 'He owns a Go settlement service on PostgreSQL and Kafka at Duna Payments, cut authorisation p99 latency to 90 ms and is on call, which is exactly the Core Payments work.',
    matching: ['Go', 'PostgreSQL', 'Kafka', 'Kubernetes', 'payments'],
    missing: [],
  },
  {
    key: 'balaton-mobility-kotlin',
    persona: 'bence',
    site: 'lever',
    title: 'Senior Kotlin Developer',
    company: 'Balaton Mobility',
    location: 'Budapest',
    language: 'en',
    description: `Balaton Mobility runs a ride-sharing and micro-mobility app in six Central European cities. Our backend handles 300,000 rides a day across bikes, scooters and cars.

We are looking for a Senior Kotlin Developer for our Rides team.

Responsibilities

- Develop and maintain Kotlin (Spring Boot) services for ride booking, pricing and payments.
- Work with PostgreSQL, Redis and RabbitMQ.
- Contribute to our move from REST to gRPC between services.
- Collaborate with mobile and product teams.

Requirements

- 5+ years of backend development, 3+ with Kotlin or Java.
- Experience with Spring Boot and relational databases.
- Familiarity with message brokers and distributed systems.
- Good English.

About the team

The Rides team is eight engineers, a product manager and a designer. We deploy several times a day, own our services in production and share an on-call rotation of one week in seven. We are migrating our largest service, pricing, from a shared database to its own this winter, and you will play a central part in it.

We offer a competitive salary, a free mobility pass, a cafeteria allowance, private health insurance, flexible working hours and a modern office in District XIII.

Apply via our careers page.`,
    postedDaysAgo: 9,
    score: 0.74,
    reason: 'He built Kotlin/Spring Boot services with PostgreSQL and RabbitMQ at Fuvar Logistics, but has worked mostly in Go for the last years and has no mobility domain experience.',
    matching: ['Kotlin', 'Spring Boot', 'PostgreSQL', 'RabbitMQ', 'gRPC'],
    missing: ['mobility domain'],
  },
  {
    key: 'pannon-energia-backend-go',
    persona: 'bence',
    site: 'manual',
    title: 'Backend fejlesztő (Go)',
    titleEn: 'Backend Developer (Go)',
    company: 'Pannon Energia Zrt.',
    location: 'Budapest',
    language: 'hu',
    description: `A Pannon Energia Zrt. Magyarország egyik meghatározó energiakereskedője, több mint 400 000 lakossági és üzleti ügyféllel. Digitális csapatunk új ügyfélplatformot épít, ehhez keresünk tapasztalt backend fejlesztőt.

Feladatok

- Go nyelvű mikroszolgáltatások tervezése és fejlesztése a számlázás és az ügyfélkiszolgálás területén.
- PostgreSQL adatbázisok tervezése és optimalizálása.
- Eseményvezérelt integrációk kialakítása Kafka segítségével.
- Részvétel a kódátnézésekben és az architektúra-döntésekben.

Elvárások

- Legalább 4 év backend fejlesztői tapasztalat, ebből legalább 2 év Go nyelven.
- PostgreSQL és Kafka ismerete.
- Docker és Kubernetes használatában szerzett tapasztalat.
- Jó kommunikációs készség magyarul és angolul.

Előny

- Számlázási vagy pénzügyi rendszerek fejlesztésében szerzett tapasztalat.
- Terraform és AWS ismerete.

Amit kínálunk

- Versenyképes fizetés és éves bónusz.
- Cafeteria és magánegészségügyi biztosítás.
- Hibrid munkavégzés, heti két irodai nappal a XI. kerületben.
- Szakmai konferenciák és képzések támogatása.

A csapat

A digitális csapat jelenleg tizenkét fejlesztőből, két tesztelőből és egy termékmenedzserből áll. Agilis módszertannal, kéthetes sprintekben dolgozunk, a kódot közösen birtokoljuk, és a szolgáltatásainkat mi magunk üzemeltetjük.

Jelentkezés önéletrajzzal a karrieroldalunkon, jelentkezési határidő: 2026. november 30. Kapcsolattartó: Németh Katalin, HR partner. A kiválasztás két körös: egy szakmai beszélgetés a csapattal, majd egy rövid rendszertervezési feladat.`,
    postedDaysAgo: 6,
    score: 0.81,
    reason: 'His Go, PostgreSQL and Kafka work and the billing-monolith split at Duna Payments fit the billing microservices well; energy retail is a new domain.',
    matching: ['Go', 'PostgreSQL', 'Kafka', 'Kubernetes', 'Terraform', 'AWS'],
    missing: ['energy domain'],
  },

  // ---------------------------------------------------------------- jonas
  {
    key: 'ostjysk-forsyning-miljoingenior',
    persona: 'jonas',
    site: 'jobindex',
    title: 'Miljøingeniør til spildevandsområdet',
    titleEn: 'Environmental engineer for wastewater',
    company: 'Østjysk Forsyning A/S',
    location: 'Aarhus',
    language: 'da',
    description: `Østjysk Forsyning renser spildevand for 350.000 borgere i Aarhus-området på seks renseanlæg. Vi søger en miljøingeniør, der vil være med til at optimere driften og reducere vores klimaaftryk.

Dine opgaver

- Følge og optimere driften af renseanlæggenes biologiske processer.
- Bearbejde og analysere proces- og laboratoriedata.
- Bidrage til projekter om reduktion af lattergasudledning og energiforbrug.
- Udarbejde indberetninger til myndighederne.

Din profil

- Du er nyuddannet eller har et par års erfaring som miljøingeniør eller lignende.
- Du har kendskab til spildevandsrensning og vandkemi.
- Du kan arbejde med data, gerne i Python eller MATLAB.
- Du taler og skriver dansk.

Vi tilbyder

Et job med mening, et grundigt introduktionsforløb, faglig sparring fra erfarne kolleger, fleksible arbejdstider og pension. Arbejdsstedet er på vores hovedkontor i Aarhus V.

Om teamet

Du bliver en del af en procesgruppe på fem ingeniører og laboranter, der arbejder tæt sammen med driftsfolkene på anlæggene. Vi har netop installeret nye online-målere for ammonium og lattergas, og vi har brug for en kollega, der kan hjælpe os med at få noget ud af alle de nye data. Du får en erfaren mentor det første år.

Kontakt driftschef Henrik Dalsgaard på 00 00 00 00. Ansøgningsfrist: 28. november 2026.`,
    postedDaysAgo: 5,
    score: 0.68,
    reason: 'His student job sampling at two treatment plants, his Python plots of sensor data and his thesis on nitrogen removal fit a graduate wastewater role; he has no experience with regulatory reporting.',
    matching: ['water chemistry', 'Python', 'MATLAB', 'wastewater treatment'],
    missing: ['regulatory reporting', 'nitrous oxide reduction'],
  },
  {
    key: 'holm-riis-graduate-climate',
    persona: 'jonas',
    site: 'jobindex',
    title: 'Graduate Engineer – Climate Adaptation',
    company: 'Holm & Riis Rådgivende Ingeniører',
    location: 'Aarhus',
    language: 'en',
    description: `Holm & Riis is an engineering consultancy of 450 people working on infrastructure, water and climate projects in Denmark and the Nordics. Our Climate Adaptation department in Aarhus is looking for graduate engineers to start in February 2027.

As a graduate you will

- Take part in projects on cloudburst management, flood risk and green urban drainage for municipalities and utilities.
- Build hydraulic models in MIKE+ or similar tools.
- Prepare maps and analyses in QGIS.
- Join our two-year graduate programme with courses and a personal mentor.

We are looking for

- A recent MSc in environmental, civil or water engineering.
- Interest in hydraulic modelling and climate adaptation.
- Experience with GIS; Python is a plus.
- Good communication skills in Danish and English.

Our graduates work on real projects from day one, typically two or three at a time, with an experienced project manager who reviews their work. Many of today's project managers started in the programme.

We offer a structured start to your career, a strong professional community, flexible hours and a social staff association.

Apply by 15 December 2026. Contact: Department Head Mette Lindhardt, +45 00 00 00 00.`,
    postedDaysAgo: 10,
    score: 0.61,
    reason: 'His MSc and QGIS skills fit the graduate profile, but his experience is in treatment processes rather than hydraulic modelling or climate adaptation, and he has not used MIKE+.',
    matching: ['QGIS', 'Python', 'environmental engineering'],
    missing: ['hydraulic modelling', 'MIKE+', 'climate adaptation'],
  },
  {
    key: 'midtvand-projektingenior',
    persona: 'jonas',
    site: 'jobbank',
    title: 'Projektingeniør til vandforsyning',
    titleEn: 'Project engineer for water supply',
    company: 'Midtvand',
    location: 'Aarhus',
    language: 'da',
    description: `Midtvand leverer drikkevand til 90.000 forbrugere i Midtjylland. Vi skal i de kommende år renovere ledningsnet og bygge to nye vandværker, og vi søger derfor en projektingeniør.

Opgaverne

- Projektledelse af mindre og mellemstore anlægsprojekter.
- Udbud og opfølgning på rådgivere og entreprenører.
- Økonomistyring og tidsplaner.
- Dialog med lodsejere og myndigheder.

Profil

- Ingeniør inden for bygge og anlæg, vand eller miljø.
- Gerne et par års erfaring med anlægsprojekter.
- Kendskab til AutoCAD og udbudsregler er en fordel.
- Kørekort B.

Om os

Midtvand er et forbrugerejet vandselskab med 45 medarbejdere. Vi har syv vandværker og 900 km ledningsnet, og vi investerer de kommende fem år 300 mio. kr. i nye anlæg og renovering. Du kommer til at sidde i anlægsafdelingen sammen med tre andre ingeniører og en tekniker.

Vi tilbyder en spændende stilling med stor selvstændighed, fleksibel arbejdstid, firmabil efter behov, pension og en sundhedsordning for alle medarbejdere.

Vi forventer at holde samtaler i uge 50, og tiltrædelse vil være 1. februar 2027 eller efter aftale.

Kontakt projektchef Ole Bækgaard på 00 00 00 00. Ansøgningsfrist: 1. december 2026.`,
    postedDaysAgo: 14,
    score: 0.47,
    reason: 'He has the engineering degree and basic AutoCAD, but the role is construction project management with tenders and budgets, where his CV shows no experience.',
    matching: ['AutoCAD', 'environmental engineering', 'water'],
    missing: ['project management', 'tendering', 'construction projects'],
  },
  // ---------------------------------------------------------------- mette: an ad on an employer's own site (Add a job)
  {
    key: 'solvang-energi-forecasting-lead',
    persona: 'mette',
    site: 'manual',
    title: 'Forecasting Lead, Energy Markets',
    company: 'Solvang Energi A/S',
    location: 'Copenhagen (hybrid)',
    language: 'en',
    description: `Solvang Energi trades the power from 1.4 GW of Danish and Swedish wind and solar parks. Our forecasts decide what we bid into the day-ahead and intraday markets, and a percentage point of forecast error is worth millions of kroner a year.

We are looking for a Forecasting Lead to own our production and price forecasts and lead a team of three data scientists. You will set the direction for our models, from gradient-boosted trees on weather ensembles to probabilistic forecasts the traders can act on, and you will work daily with the trading desk and our portfolio managers.

What you will do
Lead and develop a team of three data scientists.
Own the production forecasts for wind and solar, and the day-ahead price forecast.
Move our forecasts from point estimates to calibrated probabilistic forecasts.
Work with the trading desk on how forecasts become bids, and measure what they are worth.

What you bring
Several years of forecasting time series in production, ideally in energy.
Strong Python and SQL, and experience running models in production (MLOps).
Experience leading people or projects, and explaining uncertainty to decision makers.
Danish is an advantage, not a requirement.

We offer a hybrid workplace by Kalvebod Brygge, a pension of 12%, and a team that cares about getting forecasts right. Apply by 30 November 2026 through our careers page. Questions: Head of Trading Analytics, Rasmus Holt, +45 00 00 00 00.`,
    postedDaysAgo: 2,
    score: 0.9,
    reason: 'Her production forecasting for energy trading and team leadership match the role closely; the probabilistic forecasting is exactly her PhD work.',
    matching: ['time-series forecasting', 'Python', 'SQL', 'MLOps', 'probabilistic forecasting'],
    missing: ['people management at scale'],
  },
]
