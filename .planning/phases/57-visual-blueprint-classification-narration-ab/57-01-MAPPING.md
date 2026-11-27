# Phase 57-01: 視覺資產與推理樹對應對帳表 (57-01-MAPPING.md)

- **產出時間**：2026-11-27
- **視覺資產總數**：399 筆
- **推理樹總數**：92 棵

## 一、來源分類彙整統計

| 來源分類 (Source Category) | 筆數 | 占比 | 說明 |
|---|---:|---:|---|
| **健保批次 (nhi)** | 314 | 78.7% | `topic_key` 開頭為 `nhi-`，無推理樹對應 |
| **推理樹來源 (tree)** | 72 | 18.0% | `metadata` 具備 `tree_id`，且 doc_id 一致 72/72 |
| **知識蒸餾 (batch_distill)** | 8 | 2.0% | 來自批次蒸餾之手術專題 |
| **基層目錄 (icd)** | 4 | 1.0% | ICD-10 基層專科常見症候群 |
| **手動建立 (manual)** | 1 | 0.3% | 手動建立之視覺資產 |
| **合計** | **399** | **100.0%** | **加總精確為 399 筆，與 CONTEXT (72/314/8/4/1) 完全一致** |

## 二、推理樹覆蓋狀態

- **總推理樹數**：92 棵
- **已被資產對應之推理樹**：45 棵（共被 72 筆資產引用，部分樹具複數視角資產）
- **缺動畫之推理樹**：**47 棵**（待補足或納入黃金標準集取樣）

### 缺動畫之推理樹清單（共 47 棵）

| Tree ID | Doc ID | Title | Category |
|---|---|---|---|
| 7 | `epidermal-cyst-excision` | 未感染粉瘤微創旋轉吸引切除手術 | general |
| 8 | `paronychia-matrixectomy` | 甲溝炎嵌甲甲床重整手術 | general |
| 9 | `bromhidrosis-rotary-cutter` | 微創螺旋刀頂漿腺狐臭手術 | general |
| 10 | `endolift-laser` | Endolift 光纖內提拉手術 | general |
| 11 | `microneedle-rf` | 黃金微針電波拉提 | general |
| 12 | `scar-subcision` | 疤痕與蟹足腫光纖皮下切割治療 | general |
| 13 | `lipoma-aspiration` | 微創脂肪瘤抽吸切除手術 | general |
| 14 | `plasma-pen-electrocautery` | 等離子筆與電灼贅疣治療 | general |
| 50 | `icd-j069-uri` | 感冒（急性上呼吸道感染） | general |
| 51 | `icd-j029-pharyngitis` | 急性咽喉炎與扁桃腺炎 | general |
| 52 | `icd-j309-allergic-rhinitis` | 過敏性鼻炎 | general |
| 53 | `icd-j111-influenza` | 流行性感冒（流感） | general |
| 54 | `icd-j209-bronchitis` | 急性支氣管炎 | general |
| 55 | `icd-j0190-sinusitis` | 急性鼻竇炎 | general |
| 56 | `icd-h6690-otitis-media` | 急性中耳炎 | general |
| 57 | `icd-j45909-asthma` | 氣喘與慢性氣道發炎 | general |
| 58 | `icd-i10-hypertension` | 原發性高血壓 | general |
| 59 | `icd-e119-diabetes` | 第二型糖尿病 | general |
| 60 | `icd-e7800-hyperlipidemia` | 高脂血症與高膽固醇 | general |
| 61 | `icd-m109-gout` | 高尿酸血症與痛風 | general |
| 62 | `icd-k760-fatty-liver` | 非酒精性脂肪肝 | general |
| 63 | `icd-n189-ckd` | 慢性腎臟疾病 | general |
| 64 | `icd-a09-gastroenteritis` | 急性感染性胃腸炎 | general |
| 65 | `icd-k219-gerd` | 胃食道逆流疾病 | general |
| 66 | `icd-k2970-gastritis` | 胃炎與十二指腸炎 | general |
| 67 | `icd-k279-peptic-ulcer` | 消化性潰瘍 | general |
| 68 | `icd-k589-ibs` | 大腸激躁症 | general |
| 69 | `icd-k649-hemorrhoids` | 痔瘡與肛門靜脈曲張 | general |
| 70 | `icd-l309-eczema` | 濕疹與皮膚炎 | general |
| 71 | `icd-l509-urticaria` | 急性與慢性蕁麻疹 | general |
| 72 | `icd-l209-atopic-dermatitis` | 異位性皮膚炎 | general |
| 73 | `icd-b353-tinea` | 足癬與股癬黴菌感染 | general |
| 74 | `icd-l700-acne` | 尋常痤瘡與青春痘 | general |
| 75 | `icd-b029-herpes-zoster` | 帶狀皰疹與神經痛 | general |
| 76 | `icd-l0390-cellulitis` | 蜂窩性組織炎 | general |
| 77 | `icd-m5450-low-back-pain` | 下背痛與腰部筋膜拉傷 | general |
| 78 | `icd-m179-knee-osteoarthritis` | 膝關節退化性關節炎 | general |
| 79 | `icd-s93409-sprain-strain` | 肌腱拉傷與韌帶扭傷 | general |
| 80 | `icd-m7500-frozen-shoulder` | 肩部肌腱炎與五十肩 | general |
| 81 | `icd-m810-osteoporosis` | 骨質疏鬆症 | general |
| 82 | `icd-n3000-uti` | 急性膀胱炎與泌尿道感染 | general |
| 83 | `icd-n400-bph` | 良性前列腺肥大 | general |
| 84 | `icd-n760-vaginitis` | 陰道及外陰發炎 | general |
| 85 | `icd-n944-dysmenorrhea` | 原發性經痛 | general |
| 88 | `hao-zimmer-inductive` | 德國Zimmer強力電磁感應深層疼痛與肌力調節治療 | general |
| 90 | `general-hao-hyperbaric-oxygen` | 單人高壓氧深層組織修復與消腫療程 | general |
| 91 | `general-hao-prolotherapy-prp` | 骨科再生醫學增生與PRP注射治療 | general |

## 三、全量 399 筆視覺資產對應明細

| Asset ID | Topic Key | 來源分類 | Tree ID | Asset Doc ID | Tree Doc ID | Doc ID 吻合 | 第一幕藍圖 | 審核狀態 |
|---|---|---|---|---|---|:---:|---|---|
| 16 | `tree-epidermal-cyst-excision` | batch_distill | - | `epidermal-cyst-excision` | - | - | `cyst_excision` | approved |
| 17 | `tree-paronychia-matrixectomy` | batch_distill | - | `paronychia-matrixectomy` | - | - | `nail_matrix` | approved |
| 18 | `tree-bromhidrosis-rotary-cutter` | batch_distill | - | `bromhidrosis-rotary-cutter` | - | - | `subdermal_curettage` | approved |
| 19 | `tree-endolift-laser` | batch_distill | - | `endolift-laser` | - | - | `skin_energy` | approved |
| 20 | `tree-microneedle-rf` | batch_distill | - | `microneedle-rf` | - | - | `skin_energy` | approved |
| 21 | `tree-scar-subcision` | batch_distill | - | `scar-subcision` | - | - | `subdermal_curettage` | approved |
| 22 | `tree-lipoma-aspiration` | batch_distill | - | `lipoma-aspiration` | - | - | `subdermal_curettage` | approved |
| 23 | `tree-plasma-pen-electrocautery` | batch_distill | - | `plasma-pen-electrocautery` | - | - | `laser_action` | approved |
| 26 | `tree-3503264627-mid-lower-smas-facelift` | tree | 26 | `3503264627-mid-lower-smas-facelift` | `3503264627-mid-lower-smas-facelift` | ✅ | `deep_plane_facelift` | approved |
| 27 | `tree-3503264627-swan-neck-cervicoplasty` | tree | 45 | `3503264627-swan-neck-cervicoplasty` | `3503264627-swan-neck-cervicoplasty` | ✅ | `corset_platysmaplasty` | approved |
| 28 | `tree-3503264627-thermage-flx-rf` | tree | 24 | `3503264627-thermage-flx-rf` | `3503264627-thermage-flx-rf` | ✅ | `skin_energy` | approved |
| 29 | `tree-3503264627-epidermal-cyst-excision` | tree | 15 | `3503264627-epidermal-cyst-excision` | `3503264627-epidermal-cyst-excision` | ✅ | `cyst_excision` | approved |
| 30 | `tree-3503264627-paronychia-matrixectomy` | tree | 16 | `3503264627-paronychia-matrixectomy` | `3503264627-paronychia-matrixectomy` | ✅ | `nail_matrix` | approved |
| 31 | `tree-3503264627-bromhidrosis-rotary-cutter` | tree | 17 | `3503264627-bromhidrosis-rotary-cutter` | `3503264627-bromhidrosis-rotary-cutter` | ✅ | `subdermal_curettage` | approved |
| 32 | `tree-3503264627-endolift-laser` | tree | 18 | `3503264627-endolift-laser` | `3503264627-endolift-laser` | ✅ | `skin_energy` | approved |
| 33 | `tree-3503264627-microneedle-rf` | tree | 19 | `3503264627-microneedle-rf` | `3503264627-microneedle-rf` | ✅ | `skin_energy` | approved |
| 34 | `tree-3503264627-scar-subcision` | tree | 20 | `3503264627-scar-subcision` | `3503264627-scar-subcision` | ✅ | `subdermal_curettage` | approved |
| 35 | `tree-3503264627-lipoma-aspiration` | tree | 21 | `3503264627-lipoma-aspiration` | `3503264627-lipoma-aspiration` | ✅ | `subdermal_curettage` | approved |
| 36 | `tree-3503264627-plasma-pen-electrocautery` | tree | 22 | `3503264627-plasma-pen-electrocautery` | `3503264627-plasma-pen-electrocautery` | ✅ | `laser_action` | approved |
| 37 | `tree-3503264627-qray-frx-fractional-laser` | tree | 23 | `3503264627-qray-frx-fractional-laser` | `3503264627-qray-frx-fractional-laser` | ✅ | `laser_action` | approved |
| 38 | `tree-3503264627-facial-bone-contouring` | tree | 27 | `3503264627-facial-bone-contouring` | `3503264627-facial-bone-contouring` | ✅ | `surgical_action` | approved |
| 39 | `tree-3503264627-ultraformer-mpt-hifu` | tree | 28 | `3503264627-ultraformer-mpt-hifu` | `3503264627-ultraformer-mpt-hifu` | ✅ | `skin_energy` | approved |
| 40 | `tree-3503264627-mommy-makeover-reconstruction` | tree | 29 | `3503264627-mommy-makeover-reconstruction` | `3503264627-mommy-makeover-reconstruction` | ✅ | `surgical_action` | approved |
| 41 | `tree-3503264627-triton-laser-hair-removal` | tree | 32 | `3503264627-triton-laser-hair-removal` | `3503264627-triton-laser-hair-removal` | ✅ | `laser_action` | approved |
| 42 | `tree-3503264627-nd-yag-laser-toning` | tree | 34 | `3503264627-nd-yag-laser-toning` | `3503264627-nd-yag-laser-toning` | ✅ | `laser_action` | approved |
| 43 | `tree-3503264627-hyaluronic-acid-dermal-filler` | tree | 35 | `3503264627-hyaluronic-acid-dermal-filler` | `3503264627-hyaluronic-acid-dermal-filler` | ✅ | `dermal_support` | approved |
| 44 | `tree-3503264627-picosecond-laser-rejuvenation` | tree | 36 | `3503264627-picosecond-laser-rejuvenation` | `3503264627-picosecond-laser-rejuvenation` | ✅ | `laser_action` | approved |
| 45 | `tree-3503264627-ultherapy-focused-ultrasound` | tree | 38 | `3503264627-ultherapy-focused-ultrasound` | `3503264627-ultherapy-focused-ultrasound` | ✅ | `skin_energy` | approved |
| 46 | `tree-3503264627-full-deep-plane-facelift` | tree | 39 | `3503264627-full-deep-plane-facelift` | `3503264627-full-deep-plane-facelift` | ✅ | `deep_plane_facelift` | approved |
| 47 | `tree-3503264627-renuvion-helium-plasma` | tree | 40 | `3503264627-renuvion-helium-plasma` | `3503264627-renuvion-helium-plasma` | ✅ | `laser_action` | approved |
| 48 | `tree-3503264627-bbl-broadband-light` | tree | 42 | `3503264627-bbl-broadband-light` | `3503264627-bbl-broadband-light` | ✅ | `process_diagram` | approved |
| 49 | `tree-3503264627-varicose-vein-evlt-sclerotherapy` | tree | 43 | `3503264627-varicose-vein-evlt-sclerotherapy` | `3503264627-varicose-vein-evlt-sclerotherapy` | ✅ | `laser_action` | approved |
| 50 | `tree-3503264627-chronic-migraine-botox-decompression` | tree | 44 | `3503264627-chronic-migraine-botox-decompression` | `3503264627-chronic-migraine-botox-decompression` | ✅ | `neuromuscular` | approved |
| 51 | `tree-3503264627-overfilled-face-syndrome-correction` | tree | 46 | `3503264627-overfilled-face-syndrome-correction` | `3503264627-overfilled-face-syndrome-correction` | ✅ | `dermal_support` | approved |
| 52 | `tree-3503264627-rejuran-pdrn-skin-healer` | tree | 48 | `3503264627-rejuran-pdrn-skin-healer` | `3503264627-rejuran-pdrn-skin-healer` | ✅ | `process_diagram` | approved |
| 53 | `tree-3503264627-bulbous-nose-rhinoplasty` | tree | 49 | `3503264627-bulbous-nose-rhinoplasty` | `3503264627-bulbous-nose-rhinoplasty` | ✅ | `surgical_action` | approved |
| 54 | `tree-3503264627-chin-augmentation-genioplasty` | tree | 25 | `3503264627-chin-augmentation-genioplasty` | `3503264627-chin-augmentation-genioplasty` | ✅ | `surgical_action` | approved |
| 55 | `tree-3503264627-fue-hair-transplantation` | tree | 30 | `3503264627-fue-hair-transplantation` | `3503264627-fue-hair-transplantation` | ✅ | `process_diagram` | approved |
| 56 | `tree-3503264627-orthognathic-surgery` | tree | 31 | `3503264627-orthognathic-surgery` | `3503264627-orthognathic-surgery` | ✅ | `surgical_action` | approved |
| 57 | `tree-3503264627-hydrafacial-deep-cleansing` | tree | 33 | `3503264627-hydrafacial-deep-cleansing` | `3503264627-hydrafacial-deep-cleansing` | ✅ | `process_diagram` | approved |
| 58 | `tree-3503264627-blepharoplasty-eye-contouring` | tree | 37 | `3503264627-blepharoplasty-eye-contouring` | `3503264627-blepharoplasty-eye-contouring` | ✅ | `surgical_action` | approved |
| 59 | `tree-3503264627-structural-autologous-rhinoplasty` | tree | 41 | `3503264627-structural-autologous-rhinoplasty` | `3503264627-structural-autologous-rhinoplasty` | ✅ | `surgical_action` | approved |
| 60 | `tree-3503264627-asce-rose-exosome-regeneration` | tree | 47 | `3503264627-asce-rose-exosome-regeneration` | `3503264627-asce-rose-exosome-regeneration` | ✅ | `process_diagram` | approved |
| 69 | `tree-laser-skin-resurfacing` | tree | 1 | `laser-skin-resurfacing` | `laser-skin-resurfacing` | ✅ | `laser_action` | approved |
| 70 | `tree-asce-rose-exosome-regeneration` | tree | 47 | `3503264627-asce-rose-exosome-regeneration` | `3503264627-asce-rose-exosome-regeneration` | ✅ | `process_diagram` | approved |
| 71 | `tree-structural-autologous-rhinoplasty` | tree | 41 | `3503264627-structural-autologous-rhinoplasty` | `3503264627-structural-autologous-rhinoplasty` | ✅ | `surgical_action` | approved |
| 72 | `tree-blepharoplasty-eye-contouring` | tree | 37 | `3503264627-blepharoplasty-eye-contouring` | `3503264627-blepharoplasty-eye-contouring` | ✅ | `surgical_action` | approved |
| 73 | `tree-hydrafacial-deep-cleansing` | tree | 33 | `3503264627-hydrafacial-deep-cleansing` | `3503264627-hydrafacial-deep-cleansing` | ✅ | `process_diagram` | approved |
| 74 | `tree-orthognathic-surgery` | tree | 31 | `3503264627-orthognathic-surgery` | `3503264627-orthognathic-surgery` | ✅ | `surgical_action` | approved |
| 75 | `tree-fue-hair-transplantation` | tree | 30 | `3503264627-fue-hair-transplantation` | `3503264627-fue-hair-transplantation` | ✅ | `process_diagram` | approved |
| 76 | `tree-chin-augmentation-genioplasty` | tree | 25 | `3503264627-chin-augmentation-genioplasty` | `3503264627-chin-augmentation-genioplasty` | ✅ | `surgical_action` | approved |
| 77 | `tree-bulbous-nose-rhinoplasty` | tree | 49 | `3503264627-bulbous-nose-rhinoplasty` | `3503264627-bulbous-nose-rhinoplasty` | ✅ | `surgical_action` | approved |
| 78 | `tree-rejuran-pdrn-skin-healer` | tree | 48 | `3503264627-rejuran-pdrn-skin-healer` | `3503264627-rejuran-pdrn-skin-healer` | ✅ | `process_diagram` | approved |
| 79 | `tree-overfilled-face-syndrome-correction` | tree | 46 | `3503264627-overfilled-face-syndrome-correction` | `3503264627-overfilled-face-syndrome-correction` | ✅ | `dermal_support` | approved |
| 80 | `tree-chronic-migraine-botox-decompression` | tree | 44 | `3503264627-chronic-migraine-botox-decompression` | `3503264627-chronic-migraine-botox-decompression` | ✅ | `neuromuscular` | approved |
| 81 | `tree-varicose-vein-evlt-sclerotherapy` | tree | 43 | `3503264627-varicose-vein-evlt-sclerotherapy` | `3503264627-varicose-vein-evlt-sclerotherapy` | ✅ | `laser_action` | approved |
| 82 | `tree-bbl-broadband-light` | tree | 42 | `3503264627-bbl-broadband-light` | `3503264627-bbl-broadband-light` | ✅ | `process_diagram` | approved |
| 83 | `tree-renuvion-helium-plasma` | tree | 40 | `3503264627-renuvion-helium-plasma` | `3503264627-renuvion-helium-plasma` | ✅ | `laser_action` | approved |
| 84 | `tree-full-deep-plane-facelift` | tree | 39 | `3503264627-full-deep-plane-facelift` | `3503264627-full-deep-plane-facelift` | ✅ | `deep_plane_facelift` | approved |
| 85 | `tree-ultherapy-focused-ultrasound` | tree | 38 | `3503264627-ultherapy-focused-ultrasound` | `3503264627-ultherapy-focused-ultrasound` | ✅ | `skin_energy` | approved |
| 86 | `tree-picosecond-laser-rejuvenation` | tree | 36 | `3503264627-picosecond-laser-rejuvenation` | `3503264627-picosecond-laser-rejuvenation` | ✅ | `laser_action` | approved |
| 87 | `tree-hyaluronic-acid-dermal-filler` | tree | 35 | `3503264627-hyaluronic-acid-dermal-filler` | `3503264627-hyaluronic-acid-dermal-filler` | ✅ | `dermal_support` | approved |
| 88 | `tree-nd-yag-laser-toning` | tree | 34 | `3503264627-nd-yag-laser-toning` | `3503264627-nd-yag-laser-toning` | ✅ | `laser_action` | approved |
| 89 | `tree-triton-laser-hair-removal` | tree | 32 | `3503264627-triton-laser-hair-removal` | `3503264627-triton-laser-hair-removal` | ✅ | `laser_action` | approved |
| 90 | `tree-mommy-makeover-reconstruction` | tree | 29 | `3503264627-mommy-makeover-reconstruction` | `3503264627-mommy-makeover-reconstruction` | ✅ | `surgical_action` | approved |
| 91 | `tree-ultraformer-mpt-hifu` | tree | 28 | `3503264627-ultraformer-mpt-hifu` | `3503264627-ultraformer-mpt-hifu` | ✅ | `skin_energy` | approved |
| 92 | `tree-facial-bone-contouring` | tree | 27 | `3503264627-facial-bone-contouring` | `3503264627-facial-bone-contouring` | ✅ | `surgical_action` | approved |
| 93 | `tree-qray-frx-fractional-laser` | tree | 23 | `3503264627-qray-frx-fractional-laser` | `3503264627-qray-frx-fractional-laser` | ✅ | `laser_action` | approved |
| 94 | `tree-thermage-flx-rf` | tree | 24 | `3503264627-thermage-flx-rf` | `3503264627-thermage-flx-rf` | ✅ | `skin_energy` | approved |
| 95 | `tree-swan-neck-cervicoplasty` | tree | 45 | `3503264627-swan-neck-cervicoplasty` | `3503264627-swan-neck-cervicoplasty` | ✅ | `corset_platysmaplasty` | approved |
| 96 | `tree-mid-lower-smas-facelift` | tree | 26 | `3503264627-mid-lower-smas-facelift` | `3503264627-mid-lower-smas-facelift` | ✅ | `deep_plane_facelift` | approved |
| 97 | `tree-hifu-lifting` | tree | 6 | `hifu-lifting` | `hifu-lifting` | ✅ | `skin_energy` | approved |
| 98 | `tree-fractional-laser` | tree | 5 | `fractional-laser` | `fractional-laser` | ✅ | `laser_action` | approved |
| 99 | `tree-hyaluronic-acid-filler` | tree | 4 | `hyaluronic-acid-filler` | `hyaluronic-acid-filler` | ✅ | `dermal_support` | approved |
| 100 | `tree-electrowave-facelift` | tree | 3 | `electrowave-facelift` | `electrowave-facelift` | ✅ | `skin_energy` | approved |
| 101 | `tree-botox-injection` | tree | 2 | `botox-injection` | `botox-injection` | ✅ | `neuromuscular` | approved |
| 206 | `icd-k279-peptic-ulcer` | icd | - | - | - | - | `pathology_mechanism` | approved |
| 209 | `icd-l309-eczema` | icd | - | - | - | - | `pathology_mechanism` | approved |
| 210 | `icd-l509-urticaria` | icd | - | - | - | - | `pathology_mechanism` | approved |
| 216 | `icd-m5450-low-back-pain` | icd | - | - | - | - | `pathology_mechanism` | approved |
| 226 | `tree-general-hao-zimmer-inductive` | tree | 89 | `general-hao-zimmer-inductive` | `general-hao-zimmer-inductive` | ✅ | `process_diagram` | approved |
| 227 | `tree-hao-hyperbaric-oxygen` | tree | 87 | `hao-hyperbaric-oxygen` | `hao-hyperbaric-oxygen` | ✅ | `process_diagram` | approved |
| 230 | `tree-hao-prolotherapy-prp` | tree | 86 | `hao-prolotherapy-prp` | `hao-prolotherapy-prp` | ✅ | `pathology_mechanism` | approved |
| 231 | `nhi-w003-j0390` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 232 | `nhi-d001-k029` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 233 | `nhi-c002-m542` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 346 | `nhi-w049-b18-2` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 347 | `nhi-w043-k26-9` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 348 | `nhi-w024-i11-9` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 349 | `nhi-w041-k30` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 350 | `nhi-w019-h81-0` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 351 | `nhi-w018-h60-90` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 352 | `nhi-w014-j45-909` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 354 | `nhi-w095-n30-00` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 355 | `nhi-w080-b35-1` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 356 | `nhi-w077-l70-0` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 357 | `nhi-w076-l50-1` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 358 | `nhi-w055-m51-26` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 359 | `nhi-w054-m16-9` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 360 | `nhi-w053-m17-9` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 361 | `nhi-w052-k60-2` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 362 | `nhi-w051-k64-9` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 363 | `nhi-w046-k59-00` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 364 | `nhi-w045-k58-9` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 365 | `nhi-w044-k29-70` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 366 | `nhi-w042-k25-9` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 367 | `nhi-w039-a09` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 368 | `nhi-w020-h81-20` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 369 | `nhi-w017-h65-9` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 370 | `nhi-w016-h66-90` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 371 | `nhi-w013-j32-9` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 372 | `nhi-w012-j30-0` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 373 | `nhi-w011-j30-9` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 374 | `nhi-w009-j21-9` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 375 | `nhi-w008-j20-9` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 376 | `nhi-w007-a49-3` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 377 | `nhi-w005-j11-1` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 378 | `nhi-w004-j01-90` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 379 | `nhi-w002-j02-9` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 380 | `nhi-w001-j06-9` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 381 | `autologous-fat-grafting` | manual | - | - | - | - | `pathology_mechanism` | approved |
| 382 | `nhi-w006-u07-1` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 383 | `nhi-w010-j18-9` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 384 | `nhi-w015-j44-9` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 385 | `nhi-w021-h93-19` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 386 | `nhi-w022-h81-10` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 387 | `nhi-w025-e11-9` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 388 | `nhi-w026-r73-03` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 389 | `nhi-w027-e78-00` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 390 | `nhi-w028-e78-1` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 391 | `nhi-w029-e88-81` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 392 | `nhi-w034-n18-9` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 393 | `nhi-w035-r80-9` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 394 | `nhi-w038-e04-1` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 395 | `nhi-w040-k21-9` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 396 | `nhi-w047-k76-0` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 397 | `nhi-w050-k80-20` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 398 | `nhi-w056-m54-30` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 399 | `nhi-w057-m50-20` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 400 | `nhi-w058-s93-409` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 401 | `nhi-w059-s93-401` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 402 | `nhi-w060-m75-10` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 403 | `nhi-w061-m75-00` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 404 | `nhi-w062-m77-10` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 405 | `nhi-w063-m77-00` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 406 | `nhi-w064-m72-2` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 407 | `nhi-w065-m65-4` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 408 | `nhi-w066-g56-00` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 409 | `nhi-w067-m81-0` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 410 | `nhi-w069-g44-209` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 411 | `nhi-w070-e11-40` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 412 | `nhi-w071-b02-29` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 413 | `nhi-w072-l20-9` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 414 | `nhi-w073-l25-9` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 415 | `nhi-w074-l21-9` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 416 | `nhi-w078-l71-9` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 417 | `nhi-w079-b35-3` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 418 | `nhi-w081-b35-6` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 419 | `nhi-w083-b02-9` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 420 | `nhi-w084-b00-9` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 421 | `nhi-w085-b07-9` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 422 | `nhi-w086-l84` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 423 | `nhi-w087-b86` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 424 | `nhi-w088-l57-8` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 425 | `nhi-w089-l03-90` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 426 | `nhi-w090-l02-92` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 427 | `nhi-w091-l40-9` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 428 | `nhi-w092-l80` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 429 | `nhi-w093-l64-9` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 430 | `nhi-w094-l63-9` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 431 | `nhi-w096-n40-0` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 432 | `nhi-w097-n41-1` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 433 | `nhi-w098-n20-9` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 434 | `nhi-w099-b37-3` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 435 | `nhi-w100-n76-0` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 436 | `nhi-w101-n94-4` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 437 | `nhi-w102-n95-1` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 438 | `nhi-w103-d25-9` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 439 | `nhi-w104-n83-20` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 440 | `nhi-w105-b30-9` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 441 | `nhi-w107-h04-129` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 442 | `nhi-w108-h25-9` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 443 | `nhi-w109-h40-10` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 444 | `nhi-w110-g47-00` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 445 | `nhi-w111-f41-1` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 446 | `nhi-w112-f32-9` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 447 | `nhi-w113-g90-9` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 448 | `nhi-w031-m10-9` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 449 | `nhi-w032-i25-9` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 450 | `nhi-w036-e05-90` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 451 | `nhi-w048-b18-1` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 452 | `nhi-w075-l50-0` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 453 | `nhi-w082-b36-0` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 454 | `nhi-w106-h10-45` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 455 | `nhi-w023-i10` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 456 | `nhi-w030-e79-0` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 457 | `nhi-w033-i48-91` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 458 | `nhi-w037-e03-9` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 459 | `nhi-w201-j05-0` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 460 | `nhi-w202-j34-8` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 461 | `nhi-w203-j34-2` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 462 | `nhi-w204-j35-2` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 463 | `nhi-w205-j38-2` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 464 | `nhi-w206-h69-8` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 465 | `nhi-w207-h61-0` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 466 | `nhi-w208-b36-9` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 467 | `nhi-w209-k12-0` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 468 | `nhi-w210-k21-9` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 469 | `nhi-w211-i15-0` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 470 | `nhi-w212-e11-51` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 471 | `nhi-w213-g90-a` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 472 | `nhi-w214-i34-1` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 473 | `nhi-w215-i70-0` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 474 | `nhi-w216-i89-0` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 475 | `nhi-w217-d50-9` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 476 | `nhi-w218-d51-9` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 477 | `nhi-w219-e21-0` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 478 | `nhi-w220-e22-1` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 479 | `nhi-w221-k44-9` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 480 | `nhi-w222-d12-0` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 481 | `nhi-w223-b96-81` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 482 | `nhi-w224-k82-4` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 483 | `nhi-w225-k57-30` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 484 | `nhi-w226-k61-0` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 485 | `nhi-w227-k71-9` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 486 | `nhi-w228-k40-90` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 487 | `nhi-w229-k86-1` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 488 | `nhi-w230-k90-0` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 489 | `nhi-w231-m75-30` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 490 | `nhi-w232-g57-0` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 491 | `nhi-w233-m79-7` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 492 | `nhi-w234-m22-40` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 493 | `nhi-w235-m23-20` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 494 | `nhi-w236-m67-40` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 495 | `nhi-w237-m05-9` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 496 | `nhi-w238-m45-9` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 497 | `nhi-w239-m11-20` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 498 | `nhi-w240-m54-2` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 499 | `nhi-w241-m21-4` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 500 | `nhi-w242-r29-89` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 501 | `nhi-w243-m70-60` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 502 | `nhi-w244-m70-50` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 503 | `nhi-w245-m72-0` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 504 | `nhi-w246-l30-1` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 505 | `nhi-w247-l28-1` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 506 | `nhi-w248-l28-0` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 507 | `nhi-w249-l85-3` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 508 | `nhi-w250-l30-0` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 509 | `nhi-w251-l12-0` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 510 | `nhi-w252-d23-9` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 511 | `nhi-w253-l73-2` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 512 | `nhi-w254-r61-0` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 513 | `nhi-w255-d22-9` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 514 | `nhi-w256-l81-7` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 515 | `nhi-w257-l85-1` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 516 | `nhi-w258-q80-0` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 517 | `nhi-w259-d23-5` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 518 | `nhi-w260-l72-0` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 519 | `nhi-w261-n39-3` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 520 | `nhi-w262-n32-81` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 521 | `nhi-w263-n30-10` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 522 | `nhi-w264-n31-9` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 523 | `nhi-w265-i86-1` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 524 | `nhi-w266-n48-1` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 525 | `nhi-w267-f52-21` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 526 | `nhi-w268-n73-9` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 527 | `nhi-w269-n75-0` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 528 | `nhi-w270-n86` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 529 | `nhi-w271-e28-2` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 530 | `nhi-w272-n93-9` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 531 | `nhi-w273-n45-1` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 532 | `nhi-w274-n94-89` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 533 | `nhi-w275-n95-2` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 534 | `nhi-w276-f40-10` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 535 | `nhi-w277-f42-2` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 536 | `nhi-w278-f43-10` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 537 | `nhi-w279-f90-0` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 538 | `nhi-w280-g31-84` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 539 | `nhi-w281-g25-81` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 540 | `nhi-w282-m79-2` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 541 | `nhi-w283-g50-0` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 542 | `nhi-w284-h00-01` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 543 | `nhi-w285-h01-00` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 544 | `nhi-w286-h43-39` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 545 | `nhi-w287-h35-31` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 546 | `nhi-w288-h11-00` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 547 | `nhi-w289-h20-00` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 548 | `nhi-w290-h15-10` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 549 | `nhi-w291-r53-82` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 550 | `nhi-w292-g47-33` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 551 | `nhi-w293-n43-3` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 552 | `nhi-w294-n39-44` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 553 | `nhi-w295-r56-00` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 554 | `nhi-w296-b08-5` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 555 | `nhi-w297-j32-9` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 556 | `nhi-w298-d24-9` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 557 | `nhi-w299-n62` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 558 | `nhi-w300-m79-89` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 559 | `nhi-w301-s86-01` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 560 | `nhi-w302-g57-0` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 561 | `nhi-w303-m53-0` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 562 | `nhi-w304-g54-0` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 563 | `nhi-w305-m19-04` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 564 | `nhi-w306-m67-44` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 565 | `nhi-w307-g57-6` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 566 | `nhi-w308-m76-8` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 567 | `nhi-w309-m21-6x` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 568 | `nhi-w310-m76-6` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 569 | `nhi-w311-k20-0` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 570 | `nhi-w312-l98-2` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 571 | `nhi-w313-l92-0` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 572 | `nhi-w314-l73-9` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 573 | `nhi-w315-e78-01` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 574 | `nhi-w316-z11-1` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 575 | `nhi-w317-l50-3` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 576 | `nhi-w318-k29-40` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 577 | `nhi-w319-k80-20` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 578 | `nhi-w320-n41-1` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 579 | `nhi-c321-m26-62` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 580 | `nhi-c322-s20-20` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 581 | `nhi-c323-m65-4` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 582 | `nhi-c324-s39-9` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 583 | `nhi-c325-s93-401` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 584 | `nhi-c326-g51-0` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 585 | `nhi-c327-g50-0` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 586 | `nhi-c328-m53-0` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 587 | `nhi-c329-m43-10` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 588 | `nhi-c330-m99-02` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 589 | `nhi-c331-g57-30` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 590 | `nhi-c332-m79-7` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 591 | `nhi-c333-g57-10` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 592 | `nhi-c334-r62-5` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 593 | `nhi-c335-m72-0` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 594 | `nhi-c336-r53-82` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 595 | `nhi-c337-k21-9` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 596 | `nhi-c338-k59-00` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 597 | `nhi-c339-k58-0` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 598 | `nhi-c340-j45-9` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 599 | `nhi-c341-l30-9` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 600 | `nhi-c342-l21-9` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 601 | `nhi-c343-k29-7` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 602 | `nhi-c344-f45-8` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 603 | `nhi-c345-g44-1` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 604 | `nhi-c346-h81-0` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 605 | `nhi-c347-k81-1` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 606 | `nhi-c348-e04-1` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 607 | `nhi-c349-e88-81` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 608 | `nhi-c350-i86-8` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 609 | `nhi-c351-n97-9` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 610 | `nhi-c352-e28-2` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 611 | `nhi-c353-n93-8` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 612 | `nhi-c354-o72-2` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 613 | `nhi-c355-o92-5` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 614 | `nhi-c356-n60-2` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 615 | `nhi-c357-n73-9` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 616 | `nhi-c358-k30` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 617 | `nhi-c359-r68-1` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 618 | `nhi-c360-f95-2` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 619 | `nhi-c361-n41-1` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 620 | `nhi-c362-f52-2` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 621 | `nhi-c363-n18-9` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 622 | `nhi-c364-m10-9` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 623 | `nhi-c365-z51-0` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 624 | `nhi-c366-d70-9` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 625 | `nhi-c367-k91-3` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 626 | `nhi-c368-j31-0` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 627 | `nhi-c369-h93-1` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 628 | `nhi-c370-e11-31` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 629 | `nhi-d371-k03-2` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 630 | `nhi-d372-m26-69` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 631 | `nhi-d373-k03-3` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 632 | `nhi-d374-k04-8` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 633 | `nhi-d375-k04-99` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 634 | `nhi-d376-k03-1` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 635 | `nhi-d377-k00-5` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 636 | `nhi-d378-k02-61` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 637 | `nhi-d379-k06-1` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 638 | `nhi-d380-k06-8` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 639 | `nhi-d381-k05-31` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 640 | `nhi-d382-l43-9` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 641 | `nhi-d383-k13-21` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 642 | `nhi-d384-b37-0` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 643 | `nhi-d385-k11-6` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 644 | `nhi-d386-k10-3` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 645 | `nhi-d387-m86-8x` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 646 | `nhi-d388-m26-69` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 647 | `nhi-d389-k11-6` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 648 | `nhi-d390-m26-69` | nhi | - | - | - | - | `pathology_mechanism` | rejected |
| 649 | `nhi-d391-m26-2` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 650 | `nhi-d392-k00-6` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 651 | `nhi-d393-k00-1` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 652 | `nhi-d394-k00-6` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 653 | `nhi-d395-m26-62` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 654 | `nhi-d396-k08-23` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 655 | `nhi-d397-t85-79` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 656 | `nhi-d398-k06-8` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 657 | `nhi-d399-k05-32` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 658 | `nhi-d400-k06-8` | nhi | - | - | - | - | `pathology_mechanism` | approved |
| 659 | `tree-site-b0987ae19c-1` | tree | 92 | `site-b0987ae19c-1` | `site-b0987ae19c-1` | ✅ | `process_diagram` | approved |
