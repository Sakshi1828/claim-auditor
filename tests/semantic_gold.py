"""Hand-written answers for semantic claim understanding (what each sentence claims, not whether it is true).

GOLD_81: the 81 sentences of the six release-A test reports, in order.
PARAPHRASES: groups of differently-worded sentences that must be understood the same way.
Each label lists only what must be right; lists mean "any of these is acceptable".
"""
SUB, SUB12 = "clinical.PAM50Call_RNAseq", "clinical.PAM50_mRNA_nature2012"
ER = ["clinical.breast_carcinoma_estrogen_receptor_status", "clinical.ER_Status_nature2012"]
PR = ["clinical.breast_carcinoma_progesterone_receptor_status", "clinical.PR_Status_nature2012"]
HER2S = ["clinical.lab_proc_her2_neu_immunohistochemistry_receptor_status", "clinical.HER2_Final_Status_nature2012"]
TN = ["derived.triple_negative"] + ER + PR + HER2S
AGE = ["clinical.age_at_initial_pathologic_diagnosis", "clinical.Age_at_Initial_Pathologic_Diagnosis_nature2012"]
NODE = ["clinical.pathologic_N", "clinical.Node_Coded_nature2012", "clinical.Node_nature2012"]
SLIDES = ["slides.count", "slides.slide_kind", "coverage.slides"]
COV_SLIDES = ["coverage.slides", "slides.count", "slides.slide_kind", "slides.per_patient"]
NOT_CHECKABLE = ["needs_human_judgement", "not_in_data"]
PCT, CNT = ["percentage"], ["count", "total"]


def G(text, factual=True, cat="descriptive", agg=None, field=None, value=None, num=None, cmp=None, low=None, high=None,
      filt=None, verif="checkable", cmp_dir=None):
    d = {"text": text, "factual": factual}
    if factual:
        d.update(cat=[cat] if isinstance(cat, str) else cat, verif=[verif] if isinstance(verif, str) else verif)
        for k, v in (("agg", agg), ("field", field), ("value", value), ("num", num), ("cmp", cmp), ("low", low),
                     ("high", high), ("filt", filt), ("dir", cmp_dir)):
            if v is not None:
                d[k] = v if isinstance(v, list) or k in ("num", "low", "high") else [v]
    return d


NF = dict(factual=False)
COMP = dict(cat="comparative", agg=["group_difference"])
TREAT = dict(cat=["treatment_response"], verif=NOT_CHECKABLE)

GOLD_81 = [
    # practice brief
    G("TCGA's breast cancer cohort is one of the most widely used public cancer datasets.", **NF),
    G("Of the 1,101 primary tumors in the release, 535 have survival, mutation, copy number, RNA and protein data.",
      agg=CNT, field="coverage.all", num=535),
    G("Luminal A is the largest RNA subtype, accounting for about 62% of primary tumors with an RNA subtype call.",
      agg=PCT + ["rank"], field=SUB, value="LumA", num=62),
    G("Protein measurements add a useful layer.", **NF),
    G("Patients whose tumors had the highest ER-alpha protein responded best to hormone therapy, which suggests protein "
      "data could guide treatment research.", **TREAT),
    G("We recommend future work combine all available layers.", **NF),
    # stress report
    G("The release covers 1,101 patients and 1,247 samples, including 139 normal tissue samples and 7 metastatic samples.",
      agg=CNT, field=["cohort.patients", "cohort.samples"], num=1101),
    G("About 77% of primary tumors with a definite result were ER-positive.", agg=PCT, field=ER, value="Positive", num=77),
    G("HER2-positive tumors make up 35% of primary tumors with a definite IHC result.", agg=PCT, field=HER2S,
      value="Positive", num=35),
    G("Basal-like tumors account for 16.7% of primary tumors with an RNA subtype call, and HER2-enriched tumors for 7.9%.",
      agg=PCT, field=SUB, value="Basal", num=16.7),
    G("TP53 is the most frequently mutated gene, mutated in 45% of primary tumors with mutation data.",
      agg=PCT + ["rank"], field="mutation.TP53", num=45),
    G("PIK3CA is mutated in about 33% of primary tumors with mutation data.", agg=PCT, field="mutation.PIK3CA", num=33),
    G("Of the 3,111 slides, 1,978 are frozen sections and 1,133 are diagnostic slides.", agg=CNT, field=SLIDES, num=3111),
    G("The median age at diagnosis was 58 years.", agg="median", field=AGE, num=58),
    G("ER-alpha protein is lower in ER-negative tumors than in ER-positive tumors.", **COMP, field="protein.ERALPHA",
      cmp_dir=["lower"]),
    G("HER2 protein is higher in HER2-positive tumors.", **COMP, field="protein.HER2", cmp_dir=["higher"]),
    G("612 primary tumors have both RNA and protein data.", agg=CNT, field=["coverage.all", "coverage.rna", "coverage.protein"],
      num=612),
    G("Triple-negative tumors are about 18% of primary tumors with all three receptor results.", agg=PCT, field=TN, num=18),
    G("Basal-like tumors have worse survival than Luminal A tumors.", cat=["comparative", "associative"],
      field=["survival.OS", "survival.DSS"], verif=NOT_CHECKABLE),
    G("Tamoxifen works best in Luminal A tumors.", **TREAT),
    G("In the 2012 Nature subtype calls, Luminal A accounts for 44.3% of subtyped primary tumors.", agg=PCT, field=SUB12,
      value="Luminal A", num=44.3),
    # manifest report
    G("The slide manifest lists 3,111 slides, of which 1,133 are diagnostic and 1,978 are frozen sections.", agg=CNT,
      field=SLIDES, num=3111),
    G("The sample manifest accounts for 3,111 slides through slides_for_sample.", agg=CNT, field=SLIDES, num=3111),
    G("1,098 of the 1,101 primary tumors have at least one slide.", agg=CNT, field=COV_SLIDES, num=1098),
    G("1,062 patients have a diagnostic slide.", agg=CNT, field=COV_SLIDES, num=1062),
    G("3 primary tumors have no slides.", agg=CNT, field=COV_SLIDES, num=3),
    G("The median slide is about 338 MB.", agg="median", field="slides.size_mb", num=338),
    G("All slides together take up 1.7 TB.", agg=["total"], field="slides.size_mb", num=1.7),
    G("About 83% of slides were scanned at 40x.", agg=PCT, field="slides.objective", num=83),
    G("All slides are released under CC BY 3.0.", agg=PCT + ["existence", "count"], field="slides.license"),
    G("Each patient has 3.5 slides on average.", agg=["average_per_entity", "mean"], field=["slides.per_patient", "slides.count"],
      num=3.5),
    G("Every slide has a viewer link.", agg=PCT + ["existence", "count"], field="slides.viewer_url"),
    G("The sample manifest lists 1,247 samples from 1,101 patients, including 139 normal tissue samples and 7 metastatic "
      "samples.", agg=CNT, field=["cohort.samples", "cohort.patients"], num=1247),
    G("Most slides were scanned at 20x.", agg=PCT, field="slides.objective", num=50, cmp=["gt", "ge"]),
    G("There are 505 bottom section slides.", agg=CNT, field="slides.slide_kind", num=505),
    # next steps report
    G("Luminal A accounts for 44% of primary tumors with an RNA subtype call.", agg=PCT, field=SUB, value="LumA", num=44),
    G("TP53 is mutated in 45% of primary tumors with mutation data.", agg=PCT, field="mutation.TP53", num=45),
    G("612 primary tumors have both RNA and protein data.", agg=CNT, field=["coverage.all", "coverage.rna", "coverage.protein"],
      num=612),
    G("The median age at diagnosis was 61 years.", agg="median", field=AGE, num=61),
    G("Tamoxifen works best in Luminal A tumors.", **TREAT),
    G("Grade 3 tumors made up 41 of the cohort's lymph node findings.", cat=["descriptive"], verif=NOT_CHECKABLE),
    # real-world report
    G("TP53 and PIK3CA are the two most commonly mutated genes, each altered in roughly a third of tumors.",
      agg=PCT + ["rank"], field=["mutation.TP53", "mutation.PIK3CA"]),
    G("GATA3 mutations occur in about 11% of tumors with mutation data.", agg=PCT, field="mutation.GATA3", num=11),
    G("MAP3K1 is mutated in around 8% of cases with mutation data.", agg=PCT, field="mutation.MAP3K1", num=8),
    G("TP53 is mutated in roughly 80% of basal-like tumors.", agg=PCT, field="mutation.TP53", num=80, filt=[SUB]),
    G("PIK3CA mutations are found in about 45% of luminal A tumors.", agg=PCT, field="mutation.PIK3CA", num=45, filt=[SUB]),
    G("Between 15% and 20% of tumors are HER2-positive.", agg=PCT, field=HER2S, value="Positive", cmp=["range"], low=15,
      high=20),
    G("Roughly one in five tumors is HER2-positive.", agg=PCT, field=HER2S, value="Positive", num=20),
    G("Triple-negative tumors account for 10-15% of cases.", agg=PCT, field=TN, cmp=["range"], low=10, high=15),
    G("The median age at diagnosis is 62 years.", agg="median", field=AGE, num=62),
    G("More than half of tumors with an RNA subtype call are Luminal A.", agg=PCT, field=SUB, value="LumA", num=50,
      cmp=["gt"]),
    G("Luminal B tumors make up about a quarter of tumors with an RNA subtype call.", agg=PCT, field=SUB, value="LumB",
      num=25),
    G("The cohort includes over 1,000 breast cancer patients.", agg=CNT, field="cohort.patients", num=1000, cmp=["gt"]),
    G("Fewer than 800 primary tumors have protein data.", agg=CNT, field="coverage.protein", num=800, cmp=["lt"]),
    G("ER-negative tumors have higher ER-alpha protein levels than ER-positive tumors.", **COMP, field="protein.ERALPHA",
      cmp_dir=["higher"]),
    G("About 14% of primary tumors with survival data had a recorded death.", agg=PCT, field="survival.OS", num=14),
    G("The dataset contains roughly 3,000 pathology slides.", agg=CNT, field="slides.count", num=3000),
    G("Basal-like tumors occur more often in younger patients.", cat=["associative", "comparative"],
      field=[SUB] + AGE, verif=["checkable"] + NOT_CHECKABLE),
    G("CDH1 mutations are common in lobular carcinomas.", cat=["descriptive", "associative"], field="mutation.CDH1",
      filt=["clinical.histological_type"]),
    G("Women with HER2-positive tumors benefit from trastuzumab.", **TREAT),
    G("Nearly 4 in 5 primary tumors with a definite result are ER-positive.", agg=PCT, field=ER, value="Positive", num=80),
    # held-out report
    G("Roughly two-thirds of primary tumors with a definite result are PR-positive.", agg=PCT, field=PR, value="Positive",
      num=66.7),
    G("HER2-enriched tumors make up under 10% of tumors with an RNA subtype call.", agg=PCT, field=SUB, value="Her2",
      num=10, cmp=["lt"]),
    G("Basal-like is the third most common RNA subtype.", agg="rank", field=SUB, value="Basal"),
    G("Luminal A is the most common RNA subtype.", agg="rank", field=SUB, value="LumA"),
    G("CDH1 is mutated in 13% of primary tumors with mutation data.", agg=PCT, field="mutation.CDH1", num=13),
    G("At least 250 primary tumors carry a TP53 mutation.", agg=CNT, field="mutation.TP53", num=250, cmp=["ge"]),
    G("TP53 mutations are found in fewer than 15% of luminal A tumors.", agg=PCT, field="mutation.TP53", num=15,
      cmp=["lt"], filt=[SUB]),
    G("PIK3CA is mutated in about 45% of ER-positive tumors.", agg=PCT, field="mutation.PIK3CA", num=45, filt=ER),
    G("The release has 139 normal tissue samples and fewer than 10 metastatic samples.", agg=CNT,
      field="cohort.normal_samples", num=139),
    G("Nearly all primary tumors have survival data.", agg=PCT, field="coverage.survival", num=95, cmp=["ge"]),
    G("About 2.8 slides are available per patient.", agg=["average_per_entity", "mean"],
      field=["slides.per_patient", "slides.count"], num=2.8),
    G("More than 1,100 slides are diagnostic slides.", agg=CNT, field="slides.slide_kind", num=1100, cmp=["gt"]),
    G("Around 23% of patients are older than 65 at diagnosis.", agg=PCT, field=AGE, num=23),
    G("Fewer than 5% of patients were diagnosed before age 35.", agg=PCT, field=AGE, num=5, cmp=["lt"]),
    G("The mean age at diagnosis is about 58 years.", agg="mean", field=AGE, num=58),
    G("Over 150 deaths were recorded among primary tumors with survival data.", agg=CNT, field="survival.OS", num=150,
      cmp=["gt"]),
    G("HER2 protein is lower in HER2-positive tumors.", **COMP, field="protein.HER2", cmp_dir=["lower"]),
    G("GATA3 is mutated more often than MAP3K1.", cat="comparative", agg=["group_difference", "rank"],
      field=["mutation.GATA3", "mutation.MAP3K1"]),
    G("Luminal A and Luminal B together account for about 70% of tumors with an RNA subtype call.", agg=PCT, field=SUB,
      num=70),
    G("Copy number data is available for over 1,000 primary tumors.", agg=CNT, field="coverage.copy_number", num=1000,
      cmp=["gt"]),
]

# Each group: sentences that say the same thing. They must agree with each other AND match the label.
PARAPHRASES = [
    ("mean age 55", G("Mean patient age was 55.", agg="mean", field=AGE, num=55), [
        "Mean patient age was 55.", "Average age of patients was 55.",
        "Patients had an average age of approximately 55 years.", "On average, patients were 55 years old at diagnosis."]),
    ("Luminal A is half", G("x", agg=PCT, field=SUB, value="LumA", num=50), [
        "Half of tumors with a PAM50 call are Luminal A.", "Luminal A tumours represent 50% of subtyped cases.",
        "One in two subtyped tumors is classified as luminal A."]),
    ("TP53 mutated in a third", G("x", agg=PCT, field="mutation.TP53", num=33.3), [
        "Roughly a third of sequenced tumors harbor TP53 mutations.",
        "TP53 alterations are present in about 33% of tumors profiled for mutations.",
        "Around one-third of tumors carry a mutated TP53."]),
    ("ER-positive about 77%", G("x", agg=PCT, field=ER, value="Positive", num=77), [
        "Estrogen receptor positivity was observed in 77% of cases.", "77% of tumors were ER+.",
        "About 77 percent of breast tumors in the cohort express the estrogen receptor."]),
    ("deaths about 14%", G("x", agg=PCT, field="survival.OS", num=14), [
        "About 14% of patients died during follow-up.", "Mortality in the cohort was approximately 14%.",
        "Roughly 14 percent of patients had died by last contact."]),
    ("MYC amplified 21%", G("x", agg=PCT, field="copy_number.MYC", value="amplified", num=21), [
        "MYC is amplified in about 21% of tumors.", "High-level MYC amplification occurs in roughly 21% of tumors.",
        "Amplification of MYC was detected in 21% of samples with copy number data."]),
    ("ER-alpha protein higher in ER+", G("x", **COMP, field="protein.ERALPHA", cmp_dir=["higher"]), [
        "ER-alpha protein is higher in ER-positive than ER-negative tumors.",
        "Tumors that are estrogen-receptor positive have more ER-alpha protein than receptor-negative tumors.",
        "ERα protein levels are elevated in ER+ compared with ER− tumors."]),
    ("node involvement about half", G("x", agg=PCT, field=NODE, num=50), [
        "About half of patients had lymph node involvement.", "Roughly 50% of tumors were node-positive.",
        "Nodal metastases were present in about half of cases."]),
    ("causal", G("x", cat="causal", verif=NOT_CHECKABLE), [
        "TP53 mutations cause basal-like tumors to grow faster.", "Loss of CDH1 drives the lobular growth pattern."]),
    ("associative", G("x", cat=["associative", "comparative"],
                      field=[SUB] + ER + AGE + ["clinical.histological_type"]), [
        "Older patients are more likely to have Luminal A tumors.", "Lobular carcinomas tend to be ER-positive."]),
    ("not in the data", G("x", verif=["not_in_data", "needs_human_judgement"]), [
        "Grade 3 tumors make up 40% of the cohort.", "The Ki-67 index was above 20% in most tumors."]),
    ("not factual", G("x", **NF), [
        "These findings warrant further investigation.", "We thank the TCGA Research Network for the data."]),
]
