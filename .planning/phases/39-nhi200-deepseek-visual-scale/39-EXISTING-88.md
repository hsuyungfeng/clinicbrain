# 既有已核准動畫主題審計記錄 (Existing Animation Assets Audit)

本文件記錄 Phase 39 啟動前，正式資料庫中已存在之 **117 筆獨立動畫主題**（涵蓋 88 個核心臨床主題與昇華副本）。
這些資產目前完整保留，供後續比對、迴歸測試，並作為未來升級為嚴格 24 秒（3 幕 × 8 秒）標準之候選清單。

| 編號 | Topic Key | 主題名稱 | 來源類型 | 場景數 | 現有時長 | 藍圖清單 |
| :--- | :--- | :--- | :--- | :---: | :---: | :--- |
| 1 | `autologous-fat-grafting` | 自體脂肪移植原理 | `llm_generated` | 3 | 預設動態 | process_diagram, contrast, timeline |
| 2 | `tree-laser-skin-resurfacing` | 皮秒雷射原理圖解 | `llm_generated` | 3 | 24s | laser_action, contrast, timeline |
| 3 | `tree-botox-injection` | 肉毒桿菌素注射原理圖解 | `llm_generated` | 3 | 24s | neuromuscular, contrast, timeline |
| 4 | `tree-electrowave-facelift` | 電波拉皮原理圖解 | `llm_generated` | 3 | 24s | skin_energy, contrast, timeline |
| 5 | `tree-hyaluronic-acid-filler` | 玻尿酸填充原理圖解 | `llm_generated` | 3 | 24s | dermal_support, contrast, timeline |
| 6 | `tree-fractional-laser` | 飛梭雷射原理圖解 | `llm_generated` | 3 | 24s | laser_action, contrast, timeline |
| 7 | `tree-hifu-lifting` | 音波拉提原理圖解 | `llm_generated` | 3 | 24s | skin_energy, contrast, timeline |
| 8 | `tree-epidermal-cyst-excision` | 未感染粉瘤微創切除原理圖解 | `llm_generated` | 3 | 預設動態 | cyst_excision, contrast, timeline |
| 9 | `tree-paronychia-matrixectomy` | 甲溝炎甲床重整原理圖解 | `llm_generated` | 3 | 預設動態 | nail_matrix, contrast, timeline |
| 10 | `tree-bromhidrosis-rotary-cutter` | 螺旋刀微創狐臭手術原理圖解 | `llm_generated` | 3 | 預設動態 | subdermal_curettage, contrast, timeline |
| 11 | `tree-endolift-laser` | 光纖內提拉微創原理圖解 | `llm_generated` | 3 | 預設動態 | skin_energy, contrast, timeline |
| 12 | `tree-microneedle-rf` | 黃金微針電波原理圖解 | `llm_generated` | 3 | 預設動態 | skin_energy, contrast, timeline |
| 13 | `tree-scar-subcision` | 疤痕皮下切割原理圖解 | `llm_generated` | 3 | 預設動態 | subdermal_curettage, contrast, timeline |
| 14 | `tree-lipoma-aspiration` | 微創脂肪瘤切除原理圖解 | `llm_generated` | 3 | 預設動態 | subdermal_curettage, contrast, timeline |
| 15 | `tree-plasma-pen-electrocautery` | 等離子筆微氣化原理圖解 | `llm_generated` | 3 | 預設動態 | laser_action, contrast, timeline |
| 16 | `tree-3503264627-mid-lower-smas-facelift` | 中下臉 SMAS 筋膜深層拉皮手術原理圖解 | `llm_generated` | 3 | 24s | deep_plane_facelift, contrast, timeline |
| 17 | `tree-3503264627-swan-neck-cervicoplasty` | 天鵝頸闊頸肌縫合拉皮術原理圖解 | `llm_generated` | 3 | 24s | corset_platysmaplasty, contrast, timeline |
| 18 | `tree-3503264627-thermage-flx-rf` | Thermage FLX 鳳凰電波單極緊膚療程原理圖解 | `llm_generated` | 3 | 24s | skin_energy, contrast, timeline |
| 19 | `tree-3503264627-epidermal-cyst-excision` | 未感染粉瘤微創旋轉吸引切除手術原理圖解 | `llm_generated` | 3 | 24s | cyst_excision, contrast, timeline |
| 20 | `tree-3503264627-paronychia-matrixectomy` | 甲溝炎嵌甲甲床重整手術原理圖解 | `llm_generated` | 3 | 24s | nail_matrix, contrast, timeline |
| 21 | `tree-3503264627-bromhidrosis-rotary-cutter` | 微創螺旋刀頂漿腺狐臭手術原理圖解 | `llm_generated` | 3 | 24s | subdermal_curettage, contrast, timeline |
| 22 | `tree-3503264627-endolift-laser` | Endolift 光纖內提拉手術原理圖解 | `llm_generated` | 3 | 24s | skin_energy, contrast, timeline |
| 23 | `tree-3503264627-microneedle-rf` | 黃金微針電波拉提原理圖解 | `llm_generated` | 3 | 24s | skin_energy, contrast, timeline |
| 24 | `tree-3503264627-scar-subcision` | 疤痕與蟹足腫光纖皮下切割治療原理圖解 | `llm_generated` | 3 | 24s | subdermal_curettage, contrast, timeline |
| 25 | `tree-3503264627-lipoma-aspiration` | 微創脂肪瘤抽吸切除手術原理圖解 | `llm_generated` | 3 | 24s | subdermal_curettage, contrast, timeline |
| 26 | `tree-3503264627-plasma-pen-electrocautery` | 等離子筆與電灼贅疣治療原理圖解 | `llm_generated` | 3 | 24s | laser_action, contrast, timeline |
| 27 | `tree-3503264627-qray-frx-fractional-laser` | QRAY FRX 雙波長微創飛梭雷射原理圖解 | `llm_generated` | 3 | 24s | laser_action, contrast, timeline |
| 28 | `tree-3503264627-facial-bone-contouring` | 顏面輪廓削骨手術（顴骨弓內推縮窄與下顎骨角削減塑型）原理圖解 | `llm_generated` | 3 | 24s | surgical_action, contrast, timeline |
| 29 | `tree-3503264627-ultraformer-mpt-hifu` | Ultraformer MPT 媚必提微脈衝音波拉提療程原理 | `llm_generated` | 3 | 24s | skin_energy, contrast, timeline |
| 30 | `tree-3503264627-mommy-makeover-reconstruction` | 產後媽媽身形修復手術原理圖解 | `llm_generated` | 3 | 24s | surgical_action, contrast, timeline |
| 31 | `tree-3503264627-triton-laser-hair-removal` | Triton 海神雙波長雷射除毛療程原理圖解 | `llm_generated` | 3 | 24s | laser_action, contrast, timeline |
| 32 | `tree-3503264627-nd-yag-laser-toning` | Nd:YAG 銣雅鉻淨膚雷射均色淡斑原理圖解 | `llm_generated` | 3 | 24s | laser_action, contrast, timeline |
| 33 | `tree-3503264627-hyaluronic-acid-dermal-filler` | 玻尿酸皮下填充微整形雕塑原理圖解 | `llm_generated` | 3 | 24s | dermal_support, contrast, timeline |
| 34 | `tree-3503264627-picosecond-laser-rejuvenation` | 聚焦蜂巢皮秒雷射深層除斑與膚質重塑原理圖解 | `llm_generated` | 3 | 24s | laser_action, contrast, timeline |
| 35 | `tree-3503264627-ultherapy-focused-ultrasound` | Ultherapy 美國音波深層極線音波拉提療程原理圖解 | `llm_generated` | 3 | 24s | skin_energy, contrast, timeline |
| 36 | `tree-3503264627-full-deep-plane-facelift` | 高位深層筋膜全臉拉皮手術原理圖解 | `llm_generated` | 3 | 24s | deep_plane_facelift, contrast, timeline |
| 37 | `tree-3503264627-renuvion-helium-plasma` | Renuvion 超能電漿微創皮下縮皮緊緻術原理圖解 | `llm_generated` | 3 | 24s | laser_action, contrast, timeline |
| 38 | `tree-3503264627-bbl-broadband-light` | BBL 青萃光旗艦脈衝光嫩膚（多波段光老化精準光療）原理圖解 | `llm_generated` | 3 | 24s | process_diagram, contrast, timeline |
| 39 | `tree-3503264627-varicose-vein-evlt-sclerotherapy` | 微創下肢靜脈曲張血管內雷射閉合與泡沫硬化劑治療原理圖解 | `llm_generated` | 3 | 24s | laser_action, contrast, timeline |
| 40 | `tree-3503264627-chronic-migraine-botox-decompression` | 慢性頑固性偏頭痛肉毒桿菌素注射與周邊神經微創減壓治療原理圖解 | `llm_generated` | 3 | 24s | neuromuscular, contrast, timeline |
| 41 | `tree-3503264627-overfilled-face-syndrome-correction` | 饅化臉過度填充修復綜合治療原理圖解 | `llm_generated` | 3 | 24s | dermal_support, contrast, timeline |
| 42 | `tree-3503264627-rejuran-pdrn-skin-healer` | Rejuran 麗珠蘭野生鮭魚 DNA 多核苷酸（PN/PD | `llm_generated` | 3 | 24s | process_diagram, contrast, timeline |
| 43 | `tree-3503264627-bulbous-nose-rhinoplasty` | 蒜頭鼻雕塑與鼻頭軟骨微創縮小手術原理圖解 | `llm_generated` | 3 | 24s | surgical_action, contrast, timeline |
| 44 | `tree-3503264627-chin-augmentation-genioplasty` | 下巴美型手術（三維客製人工骨植入與下巴截骨成型術）原理圖解 | `llm_generated` | 3 | 24s | surgical_action, contrast, timeline |
| 45 | `tree-3503264627-fue-hair-transplantation` | FUE 微創毛囊單位精準植髮手術原理圖解 | `llm_generated` | 3 | 16s | process_diagram, contrast, timeline |
| 46 | `tree-3503264627-orthognathic-surgery` | 三維 數位導航正顎手術原理圖解 | `llm_generated` | 3 | 24s | surgical_action, contrast, timeline |
| 47 | `tree-3503264627-hydrafacial-deep-cleansing` | Hydrafacial 海菲秀專利水渦漩深層清潔煥膚原理圖解 | `llm_generated` | 3 | 24s | process_diagram, contrast, timeline |
| 48 | `tree-3503264627-blepharoplasty-eye-contouring` | 全方位美眸眼整形手術原理圖解 | `llm_generated` | 3 | 24s | surgical_action, contrast, timeline |
| 49 | `tree-3503264627-structural-autologous-rhinoplasty` | 結構式自體軟骨全方位隆鼻手術原理圖解 | `llm_generated` | 3 | 24s | surgical_action, contrast, timeline |
| 50 | `tree-3503264627-asce-rose-exosome-regeneration` | ASCE+ 外泌體大馬士革玫瑰幹細胞再生修復療法原理圖解 | `llm_generated` | 3 | 24s | process_diagram, contrast, timeline |
| 51 | `tree-asce-rose-exosome-regeneration` | ASCE+ 外泌體大馬士革玫瑰幹細胞再生修復療法原理圖解 | `llm_generated` | 3 | 24s | process_diagram, contrast, timeline |
| 52 | `tree-structural-autologous-rhinoplasty` | 結構式自體軟骨全方位隆鼻手術原理圖解 | `llm_generated` | 3 | 24s | surgical_action, contrast, timeline |
| 53 | `tree-blepharoplasty-eye-contouring` | 全方位美眸眼整形手術原理圖解 | `llm_generated` | 3 | 24s | surgical_action, contrast, timeline |
| 54 | `tree-hydrafacial-deep-cleansing` | Hydrafacial 海菲秀專利水渦漩深層清潔煥膚原理圖解 | `llm_generated` | 3 | 24s | process_diagram, contrast, timeline |
| 55 | `tree-orthognathic-surgery` | 三維 數位導航正顎手術原理圖解 | `llm_generated` | 3 | 24s | surgical_action, contrast, timeline |
| 56 | `tree-fue-hair-transplantation` | FUE 微創毛囊單位精準植髮手術原理圖解 | `llm_generated` | 3 | 16s | process_diagram, contrast, timeline |
| 57 | `tree-chin-augmentation-genioplasty` | 下巴美型手術（三維客製人工骨植入與下巴截骨成型術）原理圖解 | `llm_generated` | 3 | 24s | surgical_action, contrast, timeline |
| 58 | `tree-bulbous-nose-rhinoplasty` | 蒜頭鼻雕塑與鼻頭軟骨微創縮小手術原理圖解 | `llm_generated` | 3 | 24s | surgical_action, contrast, timeline |
| 59 | `tree-rejuran-pdrn-skin-healer` | Rejuran 麗珠蘭野生鮭魚 DNA 多核苷酸（PN/PD | `llm_generated` | 3 | 24s | process_diagram, contrast, timeline |
| 60 | `tree-overfilled-face-syndrome-correction` | 饅化臉過度填充修復綜合治療原理圖解 | `llm_generated` | 3 | 24s | dermal_support, contrast, timeline |
| 61 | `tree-chronic-migraine-botox-decompression` | 慢性頑固性偏頭痛肉毒桿菌素注射與周邊神經微創減壓治療原理圖解 | `llm_generated` | 3 | 24s | neuromuscular, contrast, timeline |
| 62 | `tree-varicose-vein-evlt-sclerotherapy` | 微創下肢靜脈曲張血管內雷射閉合與泡沫硬化劑治療原理圖解 | `llm_generated` | 3 | 24s | laser_action, contrast, timeline |
| 63 | `tree-bbl-broadband-light` | BBL 青萃光旗艦脈衝光嫩膚（多波段光老化精準光療）原理圖解 | `llm_generated` | 3 | 24s | process_diagram, contrast, timeline |
| 64 | `tree-renuvion-helium-plasma` | Renuvion 超能電漿微創皮下縮皮緊緻術原理圖解 | `llm_generated` | 3 | 24s | laser_action, contrast, timeline |
| 65 | `tree-full-deep-plane-facelift` | 高位深層筋膜全臉拉皮手術原理圖解 | `llm_generated` | 3 | 24s | deep_plane_facelift, contrast, timeline |
| 66 | `tree-ultherapy-focused-ultrasound` | Ultherapy 美國音波深層極線音波拉提療程原理圖解 | `llm_generated` | 3 | 24s | skin_energy, contrast, timeline |
| 67 | `tree-picosecond-laser-rejuvenation` | 聚焦蜂巢皮秒雷射深層除斑與膚質重塑原理圖解 | `llm_generated` | 3 | 24s | laser_action, contrast, timeline |
| 68 | `tree-hyaluronic-acid-dermal-filler` | 玻尿酸皮下填充微整形雕塑原理圖解 | `llm_generated` | 3 | 24s | dermal_support, contrast, timeline |
| 69 | `tree-nd-yag-laser-toning` | Nd:YAG 銣雅鉻淨膚雷射均色淡斑原理圖解 | `llm_generated` | 3 | 24s | laser_action, contrast, timeline |
| 70 | `tree-triton-laser-hair-removal` | Triton 海神雙波長雷射除毛療程原理圖解 | `llm_generated` | 3 | 24s | laser_action, contrast, timeline |
| 71 | `tree-mommy-makeover-reconstruction` | 產後媽媽身形修復手術原理圖解 | `llm_generated` | 3 | 24s | surgical_action, contrast, timeline |
| 72 | `tree-ultraformer-mpt-hifu` | Ultraformer MPT 媚必提微脈衝音波拉提療程原理 | `llm_generated` | 3 | 24s | skin_energy, contrast, timeline |
| 73 | `tree-facial-bone-contouring` | 顏面輪廓削骨手術（顴骨弓內推縮窄與下顎骨角削減塑型）原理圖解 | `llm_generated` | 3 | 24s | surgical_action, contrast, timeline |
| 74 | `tree-qray-frx-fractional-laser` | QRAY FRX 雙波長微創飛梭雷射原理圖解 | `llm_generated` | 3 | 24s | laser_action, contrast, timeline |
| 75 | `tree-thermage-flx-rf` | Thermage FLX 鳳凰電波單極緊膚療程原理圖解 | `llm_generated` | 3 | 24s | skin_energy, contrast, timeline |
| 76 | `tree-swan-neck-cervicoplasty` | 天鵝頸闊頸肌縫合拉皮術原理圖解 | `llm_generated` | 3 | 24s | corset_platysmaplasty, contrast, timeline |
| 77 | `tree-mid-lower-smas-facelift` | 中下臉 SMAS 筋膜深層拉皮手術原理圖解 | `llm_generated` | 3 | 24s | deep_plane_facelift, contrast, timeline |
| 78 | `icd-j069-uri` | 感冒（急性上呼吸道感染） | `manual` | 3 | 預設動態 | pathology_mechanism, contrast, timeline |
| 79 | `icd-j029-pharyngitis` | 急性咽喉炎與扁桃腺炎 | `manual` | 3 | 預設動態 | pathology_mechanism, contrast, timeline |
| 80 | `icd-j309-allergic-rhinitis` | 過敏性鼻炎 | `manual` | 3 | 預設動態 | pathology_mechanism, contrast, timeline |
| 81 | `icd-j111-influenza` | 流行性感冒（流感） | `manual` | 3 | 預設動態 | pathology_mechanism, contrast, timeline |
| 82 | `icd-j209-bronchitis` | 急性支氣管炎 | `manual` | 3 | 預設動態 | pathology_mechanism, contrast, timeline |
| 83 | `icd-j0190-sinusitis` | 急性鼻竇炎 | `manual` | 3 | 預設動態 | pathology_mechanism, contrast, timeline |
| 84 | `icd-h6690-otitis-media` | 急性中耳炎 | `manual` | 3 | 預設動態 | pathology_mechanism, contrast, timeline |
| 85 | `icd-j45909-asthma` | 氣喘與慢性氣道發炎 | `manual` | 3 | 預設動態 | pathology_mechanism, contrast, timeline |
| 86 | `icd-i10-hypertension` | 原發性高血壓 | `manual` | 3 | 預設動態 | pathology_mechanism, contrast, timeline |
| 87 | `icd-e119-diabetes` | 第二型糖尿病 | `manual` | 3 | 預設動態 | pathology_mechanism, contrast, timeline |
| 88 | `icd-e7800-hyperlipidemia` | 高脂血症與高膽固醇 | `manual` | 3 | 預設動態 | pathology_mechanism, contrast, timeline |
| 89 | `icd-m109-gout` | 高尿酸血症與痛風 | `manual` | 3 | 預設動態 | pathology_mechanism, contrast, timeline |
| 90 | `icd-k760-fatty-liver` | 非酒精性脂肪肝 | `manual` | 3 | 預設動態 | pathology_mechanism, contrast, timeline |
| 91 | `icd-n189-ckd` | 慢性腎臟疾病 | `manual` | 3 | 預設動態 | pathology_mechanism, contrast, timeline |
| 92 | `icd-a09-gastroenteritis` | 急性感染性胃腸炎 | `manual` | 3 | 預設動態 | pathology_mechanism, contrast, timeline |
| 93 | `icd-k219-gerd` | 胃食道逆流疾病 | `manual` | 3 | 預設動態 | pathology_mechanism, contrast, timeline |
| 94 | `icd-k2970-gastritis` | 胃炎與十二指腸炎 | `manual` | 3 | 預設動態 | pathology_mechanism, contrast, timeline |
| 95 | `icd-k279-peptic-ulcer` | 消化性潰瘍 | `manual` | 3 | 預設動態 | pathology_mechanism, contrast, timeline |
| 96 | `icd-k589-ibs` | 大腸激躁症 | `manual` | 3 | 預設動態 | pathology_mechanism, contrast, timeline |
| 97 | `icd-k649-hemorrhoids` | 痔瘡與肛門靜脈曲張 | `manual` | 3 | 預設動態 | pathology_mechanism, contrast, timeline |
| 98 | `icd-l309-eczema` | 濕疹與皮膚炎 | `manual` | 3 | 預設動態 | pathology_mechanism, contrast, timeline |
| 99 | `icd-l509-urticaria` | 急性與慢性蕁麻疹 | `manual` | 3 | 預設動態 | pathology_mechanism, contrast, timeline |
| 100 | `icd-l209-atopic-dermatitis` | 異位性皮膚炎 | `manual` | 3 | 預設動態 | pathology_mechanism, contrast, timeline |
| 101 | `icd-b353-tinea` | 足癬與股癬黴菌感染 | `manual` | 3 | 預設動態 | pathology_mechanism, contrast, timeline |
| 102 | `icd-l700-acne` | 尋常痤瘡與青春痘 | `manual` | 3 | 預設動態 | pathology_mechanism, contrast, timeline |
| 103 | `icd-b029-herpes-zoster` | 帶狀皰疹與神經痛 | `manual` | 3 | 預設動態 | pathology_mechanism, contrast, timeline |
| 104 | `icd-l0390-cellulitis` | 蜂窩性組織炎 | `manual` | 3 | 預設動態 | pathology_mechanism, contrast, timeline |
| 105 | `icd-m5450-low-back-pain` | 下背痛與腰部筋膜拉傷 | `manual` | 3 | 預設動態 | pathology_mechanism, contrast, timeline |
| 106 | `icd-m179-knee-osteoarthritis` | 膝關節退化性關節炎 | `manual` | 3 | 預設動態 | pathology_mechanism, contrast, timeline |
| 107 | `icd-s93409-sprain-strain` | 肌腱拉傷與韌帶扭傷 | `manual` | 3 | 預設動態 | pathology_mechanism, contrast, timeline |
| 108 | `icd-m7500-frozen-shoulder` | 肩部肌腱炎與五十肩 | `manual` | 3 | 預設動態 | pathology_mechanism, contrast, timeline |
| 109 | `icd-m810-osteoporosis` | 骨質疏鬆症 | `manual` | 3 | 預設動態 | pathology_mechanism, contrast, timeline |
| 110 | `icd-n3000-uti` | 急性膀胱炎與泌尿道感染 | `manual` | 3 | 預設動態 | pathology_mechanism, contrast, timeline |
| 111 | `icd-n400-bph` | 良性前列腺肥大 | `manual` | 3 | 預設動態 | pathology_mechanism, contrast, timeline |
| 112 | `icd-n760-vaginitis` | 陰道及外陰發炎 | `manual` | 3 | 預設動態 | pathology_mechanism, contrast, timeline |
| 113 | `icd-n944-dysmenorrhea` | 原發性經痛 | `manual` | 3 | 預設動態 | pathology_mechanism, contrast, timeline |
| 114 | `tree-icd-n944-dysmenorrhea` | 原發性經痛原理圖解 | `llm_generated` | 3 | 24s | pathology_mechanism, contrast, timeline |
| 115 | `tree-general-hao-zimmer-inductive` | 德國Zimmer強力電磁感應深層疼痛與肌力調節治療原理圖解 | `llm_generated` | 3 | 24s | pathology_mechanism, contrast, timeline |
| 116 | `tree-hao-hyperbaric-oxygen` | 單人高壓氧深層組織修復與消腫療程原理圖解 | `llm_generated` | 3 | 24s | process_diagram, contrast, timeline |
| 117 | `tree-hao-prolotherapy-prp` | 骨科再生醫學增生與PRP注射治療原理圖解 | `llm_generated` | 3 | 24s | pathology_mechanism, contrast, timeline |
