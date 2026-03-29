"""
analyzer.py — Logique d'analyse CV (resumeparser.app)
Module importé par Flask — sans CLI, sans Excel standalone.
"""

import os
import re
import time
import requests
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

API_URL     = "https://resumeparser.app/resume/parse"
MAX_RETRIES = 3
RETRY_DELAY = 4


# ─── APPEL API ────────────────────────────────────────────────────────────────

def parse_cv_file(file_path: str, api_key: str) -> dict:
    headers = {"Authorization": f"Bearer {api_key}"}
    for attempt in range(MAX_RETRIES):
        try:
            with open(file_path, "rb") as f:
                resp = requests.post(
                    API_URL,
                    headers=headers,
                    files={"file": (Path(file_path).name, f)},
                    timeout=60,
                )
            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code == 401:
                raise ValueError("Clé API invalide")
            elif resp.status_code == 402:
                raise ValueError("Crédit insuffisant")
            elif resp.status_code == 429:
                time.sleep(RETRY_DELAY * (attempt + 1))
                continue
            else:
                raise ValueError(f"Erreur API {resp.status_code}: {resp.text[:150]}")
        except (requests.Timeout, requests.ConnectionError):
            if attempt == MAX_RETRIES - 1:
                raise
            time.sleep(RETRY_DELAY)
    raise ValueError(f"Échec après {MAX_RETRIES} tentatives")


# ─── SCORING ─────────────────────────────────────────────────────────────────

TECH_KWS = [
    "python","django","fastapi","flask","java","spring","javascript","typescript",
    "react","angular","vue","node","php","ruby","rails","go","rust","swift","kotlin",
    "sql","postgresql","mysql","mongodb","redis","elasticsearch","kafka",
    "docker","kubernetes","aws","azure","gcp","terraform","git","linux",
    "machine learning","deep learning","tensorflow","pytorch","scikit","pandas","spark",
    "r","power bi","tableau","excel","sap","c++","c#",".net","html","css",
    "agile","scrum","jira","ci/cd","jenkins","devops","ansible","prometheus",
]

def score_candidate(raw: dict, job_title: str, job_desc: str) -> dict:
    data      = raw.get("parsed", {})
    skills    = data.get("skills") or []
    langs     = data.get("languages") or []
    cand_all  = [s.lower() for s in skills + langs]

    job_text  = f"{job_title} {job_desc}".lower()
    required  = [kw for kw in TECH_KWS if kw in job_text]

    # Compétences (40pts)
    if required:
        matched   = sum(1 for rq in required if any(rq in cs or cs in rq for cs in cand_all))
        s_skills  = round(matched / len(required) * 40, 1)
    else:
        s_skills  = 25.0

    # Expérience (30pts)
    derived   = data.get("derived") or {}
    emp_hist  = data.get("employment_history") or []
    exp       = derived.get("years_of_experience", 0) or len(emp_hist)
    s_exp     = 30 if exp>=8 else 25 if exp>=5 else 18 if exp>=3 else 10 if exp>=1 else 3

    # Formation (20pts)
    education = data.get("education") or []
    degree    = (education[0].get("degree","") if education else "").lower()
    s_edu     = (20 if any(k in degree for k in ["master","msc","m2","ingénieur","engineer","mba","phd","doctorat"])
                 else 14 if any(k in degree for k in ["bachelor","licence","bsc","bts","dut"])
                 else 8 if degree else 4)

    # Titre (10pts)
    cur_title = (data.get("title") or "").lower()
    job_kws   = [w for w in re.split(r'\W+', (job_title or "").lower()) if len(w) > 2]
    s_title   = min(10, sum(1 for kw in job_kws if kw in cur_title) * 4)

    total     = s_skills + s_exp + s_edu + s_title
    score10   = round(min(total / 10, 10.0), 1)
    adequation = min(100, int(total))
    reco      = ("Entretien recommandé" if score10 >= 8
                 else "À considérer" if score10 >= 6
                 else "Non retenu")

    return {
        "score_global":      score10,
        "score_competences": round(s_skills / 40 * 10, 1),
        "score_experience":  round(s_exp    / 30 * 10, 1),
        "score_formation":   round(s_edu    / 20 * 10, 1),
        "adequation_poste":  adequation,
        "recommandation":    reco,
    }


# ─── PROCESS UN CV ───────────────────────────────────────────────────────────

def process_one_cv(file_path: str, api_key: str, job_title: str, job_desc: str) -> dict:
    name = Path(file_path).stem
    try:
        raw      = parse_cv_file(file_path, api_key)
        parsed   = raw.get("parsed", {})
        meta     = raw.get("meta", {})
        scores   = score_candidate(raw, job_title, job_desc)

        contact  = parsed.get("contact") or {}
        education= parsed.get("education") or []
        emp_hist = parsed.get("employment_history") or []
        skills   = parsed.get("skills") or []
        languages= parsed.get("languages") or []
        derived  = parsed.get("derived") or {}
        courses  = parsed.get("courses") or []

        top_edu  = education[0] if education else {}
        exp_years= derived.get("years_of_experience", len(emp_hist))
        niveau   = ("Expert" if exp_years>=8 else "Senior" if exp_years>=5
                    else "Mid" if exp_years>=2 else "Junior")

        pros, cons = [], []
        if exp_years >= 5:            pros.append(f"{exp_years} ans d'expérience")
        elif exp_years > 0:           pros.append(f"{exp_years} an(s) d'expérience")
        else:                         cons.append("Expérience non détectée")
        if len(skills) >= 6:          pros.append(f"{len(skills)} compétences identifiées")
        elif skills:                  pros.append(f"{len(skills)} compétences")
        else:                         cons.append("Peu de compétences détectées")
        if top_edu.get("degree"):     pros.append(top_edu["degree"])
        else:                         cons.append("Formation non précisée")
        if len(languages) >= 2:       pros.append(f"{len(languages)} langues")
        if scores["score_competences"] < 5: cons.append("Compétences peu alignées au poste")
        if not contact.get("email"):  cons.append("Email non renseigné")

        resume = (parsed.get("brief") or
                  f"{parsed.get('name', name)} — {parsed.get('title','')} — "
                  f"{exp_years} ans — {', '.join(skills[:4])}")

        return {
            "_fichier":  name,
            "_statut":   "OK",
            "_balance":  meta.get("balance"),
            "nom":             parsed.get("name", name),
            "poste_actuel":    parsed.get("title", ""),
            "experience_annees": exp_years,
            "niveau":          niveau,
            "formation":       top_edu.get("degree", ""),
            "ecole":           top_edu.get("institution_name", ""),
            "localisation":    " ".join(filter(None,[contact.get("location_city",""),
                                                     contact.get("location_country","")])) or "—",
            "email":           contact.get("email", "—"),
            "telephone":       contact.get("phone", "—"),
            "linkedin":        contact.get("linkedin", ""),
            "competences_techniques": skills,
            "langues":         languages,
            "certifications":  courses,
            "resume_recruteur": resume[:300],
            "points_forts":    pros,
            "points_faibles":  cons,
            "justification":   (f"Score {scores['score_global']}/10 — "
                                f"Adéquation {scores['adequation_poste']}% au poste."),
            **scores,
        }
    except Exception as e:
        return {"_fichier": name, "_statut": "ERREUR", "_erreur": str(e)}


# ─── ANALYSE EN MASSE (GÉNÉRATEUR pour SSE) ───────────────────────────────────

def analyze_all_stream(cv_paths: list, api_key: str, job_title: str, job_desc: str):
    """
    Générateur : yield chaque résultat au fur et à mesure.
    Utilisé par Flask via Server-Sent Events.
    """
    total   = len(cv_paths)
    done    = 0
    results = []

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {
            executor.submit(process_one_cv, p, api_key, job_title, job_desc): p
            for p in cv_paths
        }
        for future in as_completed(futures):
            r    = future.result()
            done += 1
            results.append(r)
            yield done, total, r

    return results
