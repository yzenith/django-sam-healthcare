"""
loinc/codes.py
~~~~~~~~~~~~~~
Static lookup table of ~100 commonly-used LOINC codes.

Organised by clinical category.  Used as the data source for the LOINC
reference page and the /api/loinc/ search endpoint — no database required.

Structure
---------
LOINC_CODES : dict[str, dict]
    Key   = LOINC code string  (e.g. "718-7")
    Value = {
        "name":        short display name,
        "long_name":   full LOINC long common name,
        "category":    clinical category label,
        "specimen":    specimen type (Blood, Urine, etc.) or "",
        "unit":        typical reporting unit or "",
        "scale":       Qn / Ord / Nom / Nar,
    }
"""

LOINC_CODES: dict[str, dict] = {

    # ── Complete Blood Count ───────────────────────────────────────────────
    "718-7":   {"name": "Hemoglobin",          "long_name": "Hemoglobin [Mass/volume] in Blood",                         "category": "CBC",       "specimen": "Blood",  "unit": "g/dL",    "scale": "Qn"},
    "4544-3":  {"name": "Hematocrit",           "long_name": "Hematocrit [Volume Fraction] of Blood by Automated count",  "category": "CBC",       "specimen": "Blood",  "unit": "%",       "scale": "Qn"},
    "6690-2":  {"name": "WBC",                  "long_name": "Leukocytes [#/volume] in Blood by Automated count",         "category": "CBC",       "specimen": "Blood",  "unit": "10*3/uL", "scale": "Qn"},
    "777-3":   {"name": "Platelets",            "long_name": "Platelets [#/volume] in Blood by Automated count",          "category": "CBC",       "specimen": "Blood",  "unit": "10*3/uL", "scale": "Qn"},
    "789-8":   {"name": "RBC",                  "long_name": "Erythrocytes [#/volume] in Blood by Automated count",       "category": "CBC",       "specimen": "Blood",  "unit": "10*6/uL", "scale": "Qn"},
    "787-2":   {"name": "MCV",                  "long_name": "MCV [Entitic volume] by Automated count",                   "category": "CBC",       "specimen": "Blood",  "unit": "fL",      "scale": "Qn"},
    "785-6":   {"name": "MCH",                  "long_name": "MCH [Entitic mass] by Automated count",                     "category": "CBC",       "specimen": "Blood",  "unit": "pg",      "scale": "Qn"},
    "786-4":   {"name": "MCHC",                 "long_name": "MCHC [Mass/volume] by Automated count",                     "category": "CBC",       "specimen": "Blood",  "unit": "g/dL",    "scale": "Qn"},
    "770-8":   {"name": "Neutrophils %",        "long_name": "Neutrophils/100 leukocytes in Blood by Automated count",    "category": "CBC",       "specimen": "Blood",  "unit": "%",       "scale": "Qn"},
    "736-9":   {"name": "Lymphocytes %",        "long_name": "Lymphocytes/100 leukocytes in Blood by Automated count",    "category": "CBC",       "specimen": "Blood",  "unit": "%",       "scale": "Qn"},

    # ── Comprehensive Metabolic Panel ──────────────────────────────────────
    "2160-0":  {"name": "Creatinine",           "long_name": "Creatinine [Mass/volume] in Serum or Plasma",               "category": "CMP",       "specimen": "Serum",  "unit": "mg/dL",   "scale": "Qn"},
    "3094-0":  {"name": "BUN",                  "long_name": "Urea nitrogen [Mass/volume] in Serum or Plasma",            "category": "CMP",       "specimen": "Serum",  "unit": "mg/dL",   "scale": "Qn"},
    "2823-3":  {"name": "Potassium",            "long_name": "Potassium [Moles/volume] in Serum or Plasma",               "category": "CMP",       "specimen": "Serum",  "unit": "mEq/L",   "scale": "Qn"},
    "2951-2":  {"name": "Sodium",               "long_name": "Sodium [Moles/volume] in Serum or Plasma",                  "category": "CMP",       "specimen": "Serum",  "unit": "mEq/L",   "scale": "Qn"},
    "2075-0":  {"name": "Chloride",             "long_name": "Chloride [Moles/volume] in Serum or Plasma",                "category": "CMP",       "specimen": "Serum",  "unit": "mEq/L",   "scale": "Qn"},
    "1963-8":  {"name": "Bicarbonate",          "long_name": "Bicarbonate [Moles/volume] in Serum or Plasma",             "category": "CMP",       "specimen": "Serum",  "unit": "mEq/L",   "scale": "Qn"},
    "2345-7":  {"name": "Glucose",              "long_name": "Glucose [Mass/volume] in Serum or Plasma",                  "category": "CMP",       "specimen": "Serum",  "unit": "mg/dL",   "scale": "Qn"},
    "1742-6":  {"name": "ALT",                  "long_name": "Alanine aminotransferase [Enzymatic activity/volume] in Serum or Plasma", "category": "CMP", "specimen": "Serum", "unit": "U/L", "scale": "Qn"},
    "1920-8":  {"name": "AST",                  "long_name": "Aspartate aminotransferase [Enzymatic activity/volume] in Serum or Plasma","category": "CMP", "specimen": "Serum", "unit": "U/L", "scale": "Qn"},
    "6768-6":  {"name": "Alk Phosphatase",      "long_name": "Alkaline phosphatase [Enzymatic activity/volume] in Serum or Plasma",    "category": "CMP", "specimen": "Serum", "unit": "U/L", "scale": "Qn"},
    "1975-2":  {"name": "Total Bilirubin",      "long_name": "Bilirubin.total [Mass/volume] in Serum or Plasma",          "category": "CMP",       "specimen": "Serum",  "unit": "mg/dL",   "scale": "Qn"},
    "2885-2":  {"name": "Total Protein",        "long_name": "Protein [Mass/volume] in Serum or Plasma",                  "category": "CMP",       "specimen": "Serum",  "unit": "g/dL",    "scale": "Qn"},
    "1751-7":  {"name": "Albumin",              "long_name": "Albumin [Mass/volume] in Serum or Plasma",                  "category": "CMP",       "specimen": "Serum",  "unit": "g/dL",    "scale": "Qn"},
    "17861-6": {"name": "Calcium",              "long_name": "Calcium [Mass/volume] in Serum or Plasma",                  "category": "CMP",       "specimen": "Serum",  "unit": "mg/dL",   "scale": "Qn"},

    # ── Lipid Panel ────────────────────────────────────────────────────────
    "2093-3":  {"name": "Total Cholesterol",    "long_name": "Cholesterol [Mass/volume] in Serum or Plasma",              "category": "Lipids",    "specimen": "Serum",  "unit": "mg/dL",   "scale": "Qn"},
    "2085-9":  {"name": "HDL Cholesterol",      "long_name": "Cholesterol in HDL [Mass/volume] in Serum or Plasma",       "category": "Lipids",    "specimen": "Serum",  "unit": "mg/dL",   "scale": "Qn"},
    "13457-7": {"name": "LDL Cholesterol",      "long_name": "Cholesterol in LDL [Mass/volume] in Serum or Plasma by calculation", "category": "Lipids", "specimen": "Serum", "unit": "mg/dL", "scale": "Qn"},
    "2571-8":  {"name": "Triglycerides",        "long_name": "Triglyceride [Mass/volume] in Serum or Plasma",             "category": "Lipids",    "specimen": "Serum",  "unit": "mg/dL",   "scale": "Qn"},
    "9830-1":  {"name": "Chol/HDL Ratio",       "long_name": "Cholesterol.total/Cholesterol in HDL [Mass Ratio] in Serum or Plasma", "category": "Lipids", "specimen": "Serum", "unit": "ratio", "scale": "Qn"},

    # ── Thyroid ────────────────────────────────────────────────────────────
    "3016-3":  {"name": "TSH",                  "long_name": "Thyrotropin [Units/volume] in Serum or Plasma",             "category": "Thyroid",   "specimen": "Serum",  "unit": "mIU/L",   "scale": "Qn"},
    "3026-2":  {"name": "T4",                   "long_name": "Thyroxine (T4) [Mass/volume] in Serum or Plasma",           "category": "Thyroid",   "specimen": "Serum",  "unit": "ug/dL",   "scale": "Qn"},
    "3051-0":  {"name": "T3",                   "long_name": "Triiodothyronine (T3) [Mass/volume] in Serum or Plasma",    "category": "Thyroid",   "specimen": "Serum",  "unit": "ng/dL",   "scale": "Qn"},

    # ── Coagulation ────────────────────────────────────────────────────────
    "5902-2":  {"name": "PT",                   "long_name": "Prothrombin time (PT)",                                     "category": "Coag",      "specimen": "Blood",  "unit": "s",       "scale": "Qn"},
    "6301-6":  {"name": "INR",                  "long_name": "INR in Platelet poor plasma by Coagulation assay",          "category": "Coag",      "specimen": "Plasma", "unit": "{INR}",   "scale": "Qn"},
    "3173-2":  {"name": "aPTT",                 "long_name": "aPTT in Blood by Coagulation assay",                       "category": "Coag",      "specimen": "Blood",  "unit": "s",       "scale": "Qn"},

    # ── Diabetes / Glucose ─────────────────────────────────────────────────
    "4548-4":  {"name": "HbA1c",                "long_name": "Hemoglobin A1c/Hemoglobin.total in Blood",                  "category": "Diabetes",  "specimen": "Blood",  "unit": "%",       "scale": "Qn"},
    "1558-6":  {"name": "Fasting Glucose",      "long_name": "Fasting glucose [Mass/volume] in Serum or Plasma",         "category": "Diabetes",  "specimen": "Serum",  "unit": "mg/dL",   "scale": "Qn"},
    "14745-4": {"name": "Insulin",              "long_name": "Insulin [Units/volume] in Serum or Plasma",                "category": "Diabetes",  "specimen": "Serum",  "unit": "uU/mL",   "scale": "Qn"},

    # ── Cardiac Markers ────────────────────────────────────────────────────
    "10839-9": {"name": "Troponin I",           "long_name": "Troponin I.cardiac [Mass/volume] in Serum or Plasma",       "category": "Cardiac",   "specimen": "Serum",  "unit": "ng/mL",   "scale": "Qn"},
    "6598-7":  {"name": "Troponin T",           "long_name": "Troponin T.cardiac [Mass/volume] in Serum or Plasma",       "category": "Cardiac",   "specimen": "Serum",  "unit": "ng/mL",   "scale": "Qn"},
    "30934-4": {"name": "BNP",                  "long_name": "Natriuretic peptide B [Mass/volume] in Serum or Plasma",   "category": "Cardiac",   "specimen": "Serum",  "unit": "pg/mL",   "scale": "Qn"},
    "33762-6": {"name": "NT-proBNP",            "long_name": "Natriuretic peptide.B prohormone N-Terminal [Mass/volume] in Serum or Plasma", "category": "Cardiac", "specimen": "Serum", "unit": "pg/mL", "scale": "Qn"},
    "2157-6":  {"name": "CK-MB",                "long_name": "Creatine kinase.MB [Mass/volume] in Serum or Plasma",       "category": "Cardiac",   "specimen": "Serum",  "unit": "ng/mL",   "scale": "Qn"},

    # ── Renal ──────────────────────────────────────────────────────────────
    "98979-8": {"name": "eGFR",                 "long_name": "Glomerular filtration rate/1.73 sq M predicted [Volume Rate/Area] in Serum, Plasma or Blood by Creatinine-based formula (CKD-EPI)", "category": "Renal", "specimen": "Serum", "unit": "mL/min", "scale": "Qn"},
    "14959-1": {"name": "Urine Albumin/Cr",     "long_name": "Microalbumin/Creatinine [Ratio] in Urine",                 "category": "Renal",     "specimen": "Urine",  "unit": "mg/g",    "scale": "Qn"},
    "2161-8":  {"name": "Cystatin C",           "long_name": "Cystatin C [Mass/volume] in Serum or Plasma",              "category": "Renal",     "specimen": "Serum",  "unit": "mg/L",    "scale": "Qn"},

    # ── Urinalysis ─────────────────────────────────────────────────────────
    "5767-9":  {"name": "UA Appearance",        "long_name": "Appearance of Urine",                                      "category": "Urinalysis","specimen": "Urine",  "unit": "",        "scale": "Nom"},
    "5778-6":  {"name": "UA Color",             "long_name": "Color of Urine",                                           "category": "Urinalysis","specimen": "Urine",  "unit": "",        "scale": "Nom"},
    "5792-7":  {"name": "UA Glucose",           "long_name": "Glucose [Mass/volume] in Urine by Test strip",             "category": "Urinalysis","specimen": "Urine",  "unit": "mg/dL",   "scale": "Ord"},
    "5794-3":  {"name": "UA Hemoglobin",        "long_name": "Hemoglobin [Presence] in Urine by Test strip",             "category": "Urinalysis","specimen": "Urine",  "unit": "",        "scale": "Ord"},
    "5803-2":  {"name": "UA pH",                "long_name": "pH of Urine by Test strip",                                "category": "Urinalysis","specimen": "Urine",  "unit": "[pH]",    "scale": "Qn"},
    "5804-0":  {"name": "UA Protein",           "long_name": "Protein [Mass/volume] in Urine by Test strip",             "category": "Urinalysis","specimen": "Urine",  "unit": "mg/dL",   "scale": "Ord"},

    # ── Vital Signs ────────────────────────────────────────────────────────
    "8480-6":  {"name": "Systolic BP",          "long_name": "Systolic blood pressure",                                  "category": "Vitals",    "specimen": "",       "unit": "mmHg",    "scale": "Qn"},
    "8462-4":  {"name": "Diastolic BP",         "long_name": "Diastolic blood pressure",                                 "category": "Vitals",    "specimen": "",       "unit": "mmHg",    "scale": "Qn"},
    "8867-4":  {"name": "Heart Rate",           "long_name": "Heart rate",                                               "category": "Vitals",    "specimen": "",       "unit": "/min",    "scale": "Qn"},
    "9279-1":  {"name": "Respiration Rate",     "long_name": "Respiratory rate",                                         "category": "Vitals",    "specimen": "",       "unit": "/min",    "scale": "Qn"},
    "8310-5":  {"name": "Body Temperature",     "long_name": "Body temperature",                                         "category": "Vitals",    "specimen": "",       "unit": "Cel",     "scale": "Qn"},
    "2708-6":  {"name": "O2 Saturation",        "long_name": "Oxygen saturation in Arterial blood",                      "category": "Vitals",    "specimen": "",       "unit": "%",       "scale": "Qn"},
    "29463-7": {"name": "Body Weight",          "long_name": "Body weight",                                              "category": "Vitals",    "specimen": "",       "unit": "kg",      "scale": "Qn"},
    "8302-2":  {"name": "Body Height",          "long_name": "Body height",                                              "category": "Vitals",    "specimen": "",       "unit": "cm",      "scale": "Qn"},
    "39156-5": {"name": "BMI",                  "long_name": "Body mass index (BMI) [Ratio]",                            "category": "Vitals",    "specimen": "",       "unit": "kg/m2",   "scale": "Qn"},

    # ── Microbiology ──────────────────────────────────────────────────────
    "600-7":   {"name": "Blood Culture",        "long_name": "Bacteria identified in Blood by Culture",                  "category": "Micro",     "specimen": "Blood",  "unit": "",        "scale": "Nom"},
    "630-4":   {"name": "Urine Culture",        "long_name": "Bacteria identified in Urine by Culture",                  "category": "Micro",     "specimen": "Urine",  "unit": "",        "scale": "Nom"},
    "68993-5": {"name": "MRSA Screen",          "long_name": "Methicillin resistant Staphylococcus aureus (MRSA) DNA [Presence] in Specimen by NAA with probe detection", "category": "Micro", "specimen": "Nasal", "unit": "", "scale": "Ord"},

    # ── Document / Report types (used in MDM/ORU OBX-3) ───────────────────
    "18748-4": {"name": "Diagnostic Imaging",   "long_name": "Diagnostic imaging study",                                 "category": "Document",  "specimen": "",       "unit": "",        "scale": "Nar"},
    "18842-5": {"name": "Discharge Summary",    "long_name": "Discharge summary",                                        "category": "Document",  "specimen": "",       "unit": "",        "scale": "Nar"},
    "34133-9": {"name": "CCD",                  "long_name": "Summarization of episode note",                            "category": "Document",  "specimen": "",       "unit": "",        "scale": "Nar"},
    "11506-3": {"name": "Progress Note",        "long_name": "Progress note",                                            "category": "Document",  "specimen": "",       "unit": "",        "scale": "Nar"},
    "57133-1": {"name": "Referral Note",        "long_name": "Referral note",                                            "category": "Document",  "specimen": "",       "unit": "",        "scale": "Nar"},

    # ── Immunology / Serology ─────────────────────────────────────────────
    "5195-3":  {"name": "HBsAg",                "long_name": "Hepatitis B virus surface Ag [Presence] in Serum",         "category": "Serology",  "specimen": "Serum",  "unit": "",        "scale": "Ord"},
    "16935-9": {"name": "HCV Ab",               "long_name": "Hepatitis C virus Ab [Presence] in Serum",                 "category": "Serology",  "specimen": "Serum",  "unit": "",        "scale": "Ord"},
    "22696-0": {"name": "HIV-1 Ab",             "long_name": "HIV 1 Ab [Presence] in Serum",                             "category": "Serology",  "specimen": "Serum",  "unit": "",        "scale": "Ord"},
    "20447-9": {"name": "HIV RNA",              "long_name": "HIV 1 RNA [Units/volume] (viral load) in Serum or Plasma by Probe and target amplification method", "category": "Serology", "specimen": "Serum", "unit": "IU/mL", "scale": "Qn"},
}

CATEGORIES = sorted({v["category"] for v in LOINC_CODES.values()})
