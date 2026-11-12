"""Six Danish job-seeker profiles, as plain data, for the profession suite (#427, epic #426).

The six span the axes of the European job space (Eurostat EU-LFS and online-job-ad data by ISCO group): every
education level from none to a doctorate, public and private employers, local-language-only and English ads, and the
title styles (regulated, compound, fuzzy role words, employer-branded). Software engineer (master's, private, English,
fuzzy), researcher (doctorate, academic portals, English, academic ranks), accountant (vocational to master's, public
and private, standard and fuzzy titles), nurse (professional bachelor, public, regulated compound titles), shop
salesperson (no qualification, retail chains, employer-branded titles), electrician (vocational, small employers,
trade ranks).

Not a test module (no ``test_`` prefix). Every profession is a Copenhagen profile with English and Danish ads:
``config`` is what the ``keywords`` tool is asked to write (``role_targets``, ``search_keywords`` and
``topic_terms`` in both languages, no bare role noun as a topic term), ``on_topic`` and ``off_topic`` are job
titles the title gate must keep and drop, ``postings`` feed the pre-filter and prescreen, ``profile_terms`` are
the skill words a prescreen compares with, and ``rank_titles`` carry the level words of the field (postdoc,
adjunkt, svend ...) that must not count as a seniority mismatch. ``live_gap`` names the open sub-issue of
the board a profession lacks, for the live run. All names are made up.
"""

from __future__ import annotations

_LANGUAGES = ["English", "Danish"]


def _posting(title, location="Copenhagen", *, title_en=None, company="Nordlys ApS", description="", n=1):
    posting = {
        "id": f"prof-{n}", "title": title, "company": company, "location": location,
        "url": f"https://example.com/job/{n}", "description": description, "description_condensed": description,
        "source": "jobindex", "scraped_at": "2026-10-01T00:00:00Z",
    }
    if title_en:
        posting["title_en"] = title_en
    return posting


def _config(role_targets, search_keywords, topic_terms, *, remote="hybrid", exclude=None):
    return {
        "role_targets": role_targets, "search_keywords": search_keywords, "topic_terms": topic_terms,
        "remote": remote, "languages": list(_LANGUAGES), "location": "Copenhagen",
        "exclude": exclude or {"companies": ["Skygge Vikarbureau"], "keywords": ["unpaid", "ulønnet"]},
    }


PROFESSIONS = {
    "software_engineer": {
        "config": _config(
            ["Software Engineer", "Backend Developer", "Full Stack Engineer"],
            ["software engineer", "backend developer", "full stack developer", "python developer",
             "softwareudvikler", "backendudvikler", "fullstack udvikler"],
            ["software engineer", "software developer", "backend developer", "full stack", "fullstack",
             "python developer", "softwareudvikler", "backendudvikler", "udvikler"]),
        "on_topic": [
            "Software Engineer", "Senior Software Engineer", "Backend Developer", "Full Stack Developer",
            "Python Developer", "Softwareudvikler", "Backendudvikler", "Fullstack udvikler"],
        "off_topic": ["Sygeplejerske", "HR Business Partner", "Revisor", "Pastry Chef"],
        "postings": [
            _posting("Senior Software Engineer", company="Skyfunktion ApS", n=1,
                     description="python backend api postgres docker kubernetes"),
            _posting("Softwareudvikler", title_en="Software Developer", company="Datasmedjen", n=2,
                     description="python backend api postgres docker"),
            _posting("Backend Developer", company="Betalingsnet", n=3,
                     description="backend python go api kubernetes"),
        ],
        "profile_terms": {"python", "api", "postgres", "docker", "kubernetes"},
        "rank_titles": [],
    },
    "researcher": {
        "config": _config(
            ["Postdoc in Physics", "Assistant Professor of Physics", "Research Scientist, Astrophysics"],
            ["postdoc physics", "assistant professor physics", "astrophysics", "biophysics", "adjunkt fysik",
             "postdoc fysik", "lektor fysik", "forsker fysik", "astrofysik", "kvantefysik"],
            ["postdoc", "postdoc physics", "physics", "astrophysics", "biophysics", "quantum", "adjunkt",
             "lektor", "professor", "fysik", "astrofysik", "biofysik", "kvante", "forsker",
             "Niels Bohr Institute", "Niels Bohr Institutet", "Institut for Fysik og Astronomi", "DTU Physics",
             "DTU Fysik", "Department of Physics and Astronomy"]),
        "on_topic": [
            "Postdoc in Astrophysics", "Biophysics Postdoc", "Assistant Professor in Quantum Physics",
            "Adjunkt i fysik", "Lektor i astrofysik", "Postdoc i kvantefysik", "Research Scientist, Physics",
            "Professor of Experimental Physics", "Tenure-track Assistant Professor, Niels Bohr Institute"],
        "off_topic": ["Fysioterapeut", "Physiotherapist", "Sales Manager", "Kok"],
        "postings": [
            _posting("Postdoc in Astrophysics", company="Niels Bohr Institute Test", n=1,
                     description="astrophysics simulations python cosmology publications"),
            _posting("Adjunkt i fysik", title_en="Assistant Professor in Physics", company="Universitet Syd", n=2,
                     description="physics teaching research python publications"),
            _posting("Lektor i kvantefysik", title_en="Associate Professor in Quantum Physics",
                     company="Universitet Nord", n=3, description="quantum physics research teaching"),
        ],
        "profile_terms": {"physics", "python", "simulations", "publications", "research"},
        "rank_titles": ["Postdoc in Astrophysics", "Adjunkt i fysik", "Lektor i kvantefysik"],
    },
    "accountant": {
        "config": _config(
            ["Accountant", "Financial Accountant", "Bookkeeper"],
            ["accountant", "financial accountant", "bookkeeper", "accounts payable", "bogholder", "regnskabsmedarbejder",
             "regnskabsassistent", "økonomimedarbejder", "revisorassistent"],
            # Danish compounds carry the field at the end (kreditorbogholder) or the start (regnskabschef).
            ["accountant", "accounting", "bookkeeper", "bookkeeping", "accounts payable", "accounts receivable",
             "general ledger", "*bogholder", "bogholderi", "regnskab*", "økonomimedarbejder", "økonomiassistent",
             "revisorassistent"]),
        "on_topic": [
            "Accountant", "Senior Accountant", "Financial Accountant", "Bookkeeper", "Accounts Payable Specialist",
            "Bogholder", "Kreditorbogholder", "Regnskabsmedarbejder", "Regnskabsassistent til revisionsfirma",
            "Økonomimedarbejder med flair for bogholderi"],
        "off_topic": ["Key Account Manager", "Account Executive", "Sygeplejerske", "Software Engineer"],
        "postings": [
            _posting("Financial Accountant", company="Havn Logistik", n=1,
                     description="month-end closing reconciliation general ledger accounts payable vat reporting"),
            _posting("Bogholder", title_en="Bookkeeper", company="Fjord Energi", n=2,
                     description="bogføring afstemning moms kreditorer regnskab"),
            _posting("Regnskabsmedarbejder", title_en="Accounting Officer", company="Lysfabrik A/S", n=3,
                     description="regnskab afstemning bogføring årsregnskab"),
        ],
        "profile_terms": {"bogføring", "afstemning", "regnskab", "reconciliation", "general ledger"},
        "rank_titles": ["Regnskabsassistent til revisionsfirma"],
    },
    "nurse": {
        "config": _config(
            ["Nurse", "Intensive Care Nurse", "Registered Nurse"],
            ["nurse", "registered nurse", "intensive care nurse", "sygeplejerske", "intensivsygeplejerske",
             "anæstesisygeplejerske", "afdelingssygeplejerske", "hjemmesygeplejerske"],
            ["nurse", "sygeplejerske", "intensivsygeplejerske", "anæstesisygeplejerske", "afdelingssygeplejerske",
             "hjemmesygeplejerske", "sygepleje", "intensive care", "ward nurse"],
            remote="no"),
        "on_topic": [
            "Sygeplejerske", "Intensivsygeplejerske", "Anæstesisygeplejerske", "Afdelingssygeplejerske",
            "Hjemmesygeplejerske", "Registered Nurse", "Intensive Care Nurse", "Sygeplejerske til Kardiologisk Afdeling",
            "Operationssygeplejerske", "Udviklingssygeplejerske"],
        "off_topic": ["Fysioterapeut", "Læge", "Software Engineer", "Social- og sundhedsassistent"],
        "postings": [
            _posting("Intensivsygeplejerske", location="Hillerød", title_en="Intensive Care Nurse",
                     company="Region Nord Hospital", n=1, description="intensiv sygepleje patienter vagter"),
            _posting("Sygeplejerske", location="Rigshospitalet, København", company="Rigshospitalet Test", n=2,
                     description="sygepleje patienter afdeling vagter"),
            _posting("Hjemmesygeplejerske", location="Roskilde", title_en="Home Care Nurse",
                     company="Roskilde Kommune Test", n=3, description="hjemmepleje sygepleje borgere"),
            _posting("Registered Nurse", location="Køge", company="Sjælland Sundhed", n=4,
                     description="nursing patients ward shifts"),
        ],
        "profile_terms": {"sygepleje", "patienter", "vagter", "nursing", "ward"},
        "rank_titles": ["Afdelingssygeplejerske"],
    },
    "shop_sales": {
        "config": _config(
            ["Shop Assistant", "Sales Assistant", "Retail Sales Associate"],
            ["shop assistant", "sales assistant", "retail sales associate", "store associate", "butiksassistent",
             "butiksmedarbejder", "salgsassistent", "ekspedient", "kassemedarbejder"],
            # Shop and chain ads name the store rather than the job ("... til vores butik i Lyngby").
            ["shop assistant", "sales assistant", "sales associate", "store associate", "butik*", "salgsassistent",
             "ekspedient", "kassemedarbejder", "kasseassistent"],
            remote="no"),
        "on_topic": [
            "Butiksassistent", "Butiksmedarbejder", "Salgsassistent", "Ekspedient", "Shop Assistant",
            "Sales Assistant", "Retail Sales Associate", "Deltidsmedarbejder til vores butik i Lyngby",
            "Kassemedarbejder", "Butiksassistent på deltid"],
        "off_topic": ["Lagermedarbejder", "Chauffør", "Sygeplejerske", "Software Engineer"],
        "postings": [
            _posting("Butiksassistent", location="Lyngby", title_en="Shop Assistant", company="Lysbutikken",
                     n=1, description="kunder kasse butik vareopfyldning salg weekend"),
            _posting("Salgsassistent til modebutik", location="København", title_en="Sales Assistant, Fashion Store",
                     company="Nordtøj", n=2, description="salg kunder butik kasse"),
            _posting("Shop Assistant", location="Copenhagen", company="Havnens Boghandel", n=3,
                     description="customer service till shop sales stock part-time"),
        ],
        "profile_terms": {"kunder", "kasse", "butik", "salg", "customer service"},
        "rank_titles": ["Butiksassistent"],
    },
    "electrician": {
        "config": _config(
            ["Electrician", "Service Electrician", "Journeyman Electrician"],
            ["electrician", "service electrician", "elektriker", "serviceelektriker", "autoriseret elektriker",
             "svend elektriker", "elinstallatør"],
            ["electrician", "elektriker", "serviceelektriker", "installatør", "autoriseret elektriker",
             "elektrikersvend", "svend elektriker", "el-installatør"],
            remote="no"),
        "on_topic": [
            "Elektriker", "Serviceelektriker", "Autoriseret elektriker", "Elektrikersvend",
            "Electrician", "Service Electrician", "El-installatør", "Elektriker til servicefirma",
            "Lærling elektriker"],
        "off_topic": ["Sygeplejerske", "Software Engineer", "Tømrer", "Revisor"],
        "postings": [
            _posting("Serviceelektriker", location="Roskilde", title_en="Service Electrician",
                     company="Strømsmed ApS", n=1, description="elinstallation service fejlfinding autorisation"),
            _posting("Elektriker", location="København", company="Lysnet Installation", n=2,
                     description="elinstallation fejlfinding autorisation tavler"),
            _posting("Svend elektriker", location="Hillerød", title_en="Journeyman Electrician",
                     company="Nordstrøm El", n=3, description="elinstallation svend autorisation"),
            _posting("Electrician", location="Køge", company="Sjælland El", n=4,
                     description="electrical installation troubleshooting"),
        ],
        "profile_terms": {"elinstallation", "fejlfinding", "autorisation", "installation", "tavler"},
        "rank_titles": ["Svend elektriker", "Lærling elektriker"],
    },
}
