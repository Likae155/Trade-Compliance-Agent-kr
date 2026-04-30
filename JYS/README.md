# Trade Document Test Scenarios (Legal Risk & Discrepancies)

본 폴더는 무역 계약 리스크 검토 에이전트의 성능 검증을 위한 테스트 데이터셋을 포함합니다. 총 100개의 시나리오가 준비되어 있습니다.

## 1. 데이터셋 개요
- **Scenario 1~3**: **Clean Data (Gold Standard)**. 서류 간 정합성이 완벽하며 법적 결함이 없는 정상 거래 샘플.
- **Scenario 4~100**: **Risk Data**. 실무적/법률적 리스크가 의도적으로 삽입된 샘플. AI의 리스크 탐지 및 법률 자문 능력을 테스트함.

---

## 2. 시나리오별 리스크 상세 (1~100)

| ID | 리스크 1 (Primary Risk) | 근거 법령 1 | 리스크 2 (Secondary Risk) | 근거 법령 2 | 의도적 불일치 (Document Discrepancies) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **01** | 없음 (정상 데이터) | - | 없음 | - | - |
| **02** | 없음 (정상 데이터) | - | 없음 | - | - |
| **03** | 없음 (정상 데이터) | - | 없음 | - | - |
| **04** | Incoterms Misuse (FOB for Air) | Incoterms 2020 (FOB A2/A9) | Cost Allocation (Warehouse fees to Buyer) | Incoterms 2020 Cost Allocation | - |
| **05** | CISG Reservation Country (Argentina) | CISG Art 12/96 | Legal Ambiguity (Local law priority) | CISG/Local Law Conflict | - |
| **06** | UCP 600 Strict Compliance (Unsigned Invoice) | UCP 600 Art 18 | Currency Mixture (EUR vs USD) | UCP 600 Art 18 (Currency Consistency) | - |
| **07** | Description Discrepancy (Detail vs General) | UCP 600 Art 18 (c) | Weight Error (Gross < Net) | UCP 600 Art 14 (Data Consistency) | - |
| **08** | Narrow Force Majeure scope | CISG Art 79 | Unfair Termination Rights | UNIDROIT Art 7.1.7 | - |
| **09** | IP Warranty Disclaimer | CISG Art 42 | Missing Confidentiality Clause | Trade Secret Protection | - |
| **10** | Missing ROT (Reservation of Title) Clause | SGA Art 19 | Interest Rate Conflict (6% vs 2%) | Commercial Law Art 54 | - |
| **11** | Missing Inspection Period | CISG Art 38 | Excessive Notice Deadline (48h) | CISG Art 39 | - |
| **12** | Partial Shipment Prohibition Violation | UCP 600 Art 31 | Vessel Age Restriction Violation | Institute Cargo Clauses (ICC) | - |
| **13** | Insufficient Insurance Coverage (ICC A vs C) | UCP 600 Art 28 | Wrong Insurance Beneficiary | UCP 600 Art 28 | - |
| **14** | Foreign Trade Act Violation (Strategic Goods) | Foreign Trade Act Art 19 | Origin Misidentification (Korea vs S.Korea) | Foreign Trade Act Art 33 | - |
| **15** | Foreign Exchange Act Violation (Set-off) | Foreign Exchange Act Art 16 | Bank Fee SHA Clause Violation | UCP 600 Art 37 | - |
| **16** | Liability Cap Setting (10%) | Adhesion Contract Act Art 7 | Warranty Period Conflict (1y vs 90d) | UCTA (Reasonableness Test) | - |
| **17** | Arbitration Seat-Institution Mismatch | Arbitration Act Art 21 | Missing Authorized Signatory | UNIDROIT Art 2.2.5 | - |
| **18** | CISG Exclusion Error (Implicit) | CISG Art 1/6 | Unconditional Exemption for Delay | CISG Art 79 (Exemption) | - |
| **19** | Stale Documents (Over 21 days) | UCP 600 Art 14 (c) | Shipping Mark Discrepancy | UCP 600 Art 14 | - |
| **20** | Double Insurance (Overlap) | Commercial Law Art 672 | Insurance Amount Deficiency (110% req) | UCP 600 Art 28 | - |
| **21** | 준거법 미지정 (Silence on Governing Law) | CISG Art. 1 / PIL Act | 국제사법에 의한 불예측한 법 적용 | Hague Convention 1955 | **invoice**: AI Noted Discrepancy (L/C shipment deadline was 2024-03-01; shipment occurred 2024-03-02. This is a LATE SHIPMENT discrepancy.) |
| **22** | 재판관할권 미합의 (No Jurisdiction Clause) | Civil Procedure Act | 피고 소재지 원격 소송 비용 발생 | Brussels I Regulation | **invoice**: AI Noted Discrepancy (B/L date 2023-11-21 exceeds L/C latest shipment date of 2023-11-20) |
| **23** | 전략물자 무허가 수출 합의 | 대외무역법 제19조 | 수출 통제 위반에 따른 계약 무효 | 대외무역법 제29조 | **invoice**: AI Noted Discrepancy (Intentional Discrepancy: Shipping date 2024-10-16 exceeds latest shipment date 2024-10-15.) |
| **24** | 소멸시효 단축 특약 (6개월 미만) | 상법 제64조 | 강행규정 위반으로 인한 조항 무효 | 민법 제184조 | **invoice**: AI Noted Discrepancy (LATE SHIPMENT: B/L date 2024-03-16 exceeds L/C latest shipment date of 2024-03-15.) |
| **25** | 수입 원산지 표시 의무 면제 조항 | 대외무역법 제33조 | 세관 통관 불허 및 형사 처벌 리스크 | 대외무역법 제53조 | **invoice**: AI Noted Discrepancy (Intentional Discrepancy: Shipping date 2023-10-26 is one day after the L/C latest shipment date 2023-10-25.) |
| **26** | 비거주자 간 채권 상계 미신고 | 외국환거래법 제16조 | 외환 당국 보고 의무 위반 과태료 | 외국환거래규정 제5-4조 | **invoice**: AI Noted Discrepancy (Document shows shipment date 2024-07-02, which violates the L/C latest shipment date of 2024-06-30.) |
| **27** | 부당한 판매가격 유지 강제 (Vertical) | 공정거래법 제46조 | 독점규제법 위반에 따른 과징금 | 공정거래법 제125조 | **invoice**: AI Noted Discrepancy (B/L date 2023-12-02 exceeds latest shipment date 2023-11-30) |
| **28** | 매도인의 손해배상책임 전면 면책 | 약관법 제7조 | 고객에게 부당하게 불리한 조항 무효 | CISG Art. 4 | **invoice**: AI Noted Discrepancy (Documentary Discrepancy: BL date (2023-11-17) is later than LC latest shipment date (2023-11-15).) |
| **29** | DDP 조건임에도 매수인에게 수입관세 전가 | Incoterms 2020 (DDP) | 계약 내용과 인코텀즈 정의의 정면 충돌 | 계약 우선 원칙 (Precedence) | **invoice**: AI Noted Discrepancy (B/L date 2023-11-16 exceeds latest shipment date 2023-11-15 (Discrepancy: Late Shipment).) |
| **30** | 물품 검사 기간의 극단적 단축 (24시간) | CISG Art. 38 | 잠재적 하자 발견권의 실질적 박탈 | CISG Art. 39 | **invoice**: AI Noted Discrepancy (B/L date exceeds latest shipment date by 1 day) |
| **31** | 기술도입료(Royalty) 송금 절차 누락 | 외국환거래법 제18조 | 지식재산권 대가 지급 불능 및 연체 | 외국환거래법 제32조 | **invoice**: AI Noted Discrepancy (Invoice excludes the 5000 USD software royalty fee, failing to meet requirements of Foreign Exchange Transaction Act.) |
| **32** | 상사 지연이자율 초과 설정 (연 30% 등) | 상법 제54조 | 이자제한법 및 약관법 위반 가능성 | 약관법 제6조 | **invoice**: AI Noted Discrepancy (B/L date (July 16) is after latest shipment date (July 15)) |
| **33** | FOB 조건에서 매도인이 본선 선적비 거부 | Incoterms 2020 (FOB) | 비용 분담에 대한 실무적 마찰 | Incoterms 2020 B9 | **invoice**: AI Noted Discrepancy (B/L date exceeds L/C latest shipment date by 1 day; Seller refused to pay THC (Terminal Handling Charges) as per FOB interpretation.) |
| **34** | 독점권 부여 후 타 지역 판매 전면 금지 | 공정거래법 제45조 | 구속조건부 거래 행위 해당 여부 | 공정거래법 시행령 | **invoice**: AI Noted Discrepancy (B/L date (Nov 2) exceeds L/C latest shipment date (Oct 30) - Discrepancy present.) |
| **35** | 신용장 독립/추상성 원칙 배제 시도 | UCP 600 Art. 4 | 은행의 지급 거절권 상실 리스크 | UCP 600 Art. 5 | **invoice**: AI Noted Discrepancy (Invoice amount exceeds L/C amount by $500) |
| **36** | 위험 이전 시점 불명확 (Shipment Date만 명시) | CISG Art. 67 | 운송 중 사고 발생 시 책임 소재 분쟁 | Incoterms 2020 A3 | **invoice**: AI Noted Discrepancy (B/L Date (2024-07-02) exceeds Latest Shipment Date (2024-06-30)) |
| **37** | 수입 요건 확인 면제 물품의 재판매 금지 위반 | 대외무역법 제12조 | 용도 외 사용에 따른 부정 수입죄 | 대외무역법 제53조 | - |
| **38** | 청약의 철회 불능 기간 미설정 | CISG Art. 16 | 승낙 전 계약 파기 가능성 상존 | CISG Art. 15 | **invoice**: AI Noted Discrepancy (B/L date 2023-11-21 exceeds L/C latest shipment date 2023-11-20.) |
| **39** | 제재 대상국(Sanctioned) 선박 이용 지시 | 국제평화유지법 / 대외무역법 | 대금 송금 차단 및 블랙리스트 등재 | 외국환거래법 | - |
| **40** | 과도한 위약벌 설정 (계약금의 5배 등) | 민법 제398조 | 법원 직권 감액 및 약관법 위반 | 약관법 제8조 | **invoice**: AI Noted Discrepancy (Invoice total (100,000) exceeds L/C amount (99,000) by 1,000 USD.) |
| **41** | 가공무역 수입 물품의 국내 유출 합의 | 대외무역법 제16조 | 외화획득용 원료 관리 의무 위반 | 대외무역법 시행령 | - |
| **42** | 운송인 책임 제한 배제 특약 (매도인에게 유리) | 상법 제797조 | 해상법상 강행규정 위반으로 무효 | 상법 제806조 | **invoice**: AI Noted Discrepancy (B/L date 2023-10-02 exceeds latest shipment date 2023-09-30.) |
| **43** | 지식재산권 침해 시 매수인 면책 조항 | CISG Art. 42 | 제3자 권리 주장에 대한 방어권 부재 | Trade Secret Act | - |
| **44** | FCA 조건 시 적재 의무(Loading) 명시 누락 | Incoterms 2020 (FCA) | 영업장 외 장소 인도 시 비용 주체 모호 | Incoterms 2020 A2 | **invoice**: AI Noted Discrepancy (Late shipment: BL date 2024-06-16 exceeds latest shipment date of 2024-06-15.) |
| **45** | 구두 계약의 효력 전면 부인 (Entire Agreement) | CISG Art. 11 / 29 | 과거 합의 사항의 증거 능력 상실 | CISG Art. 8 | **invoice**: AI Noted Discrepancy (Intentional discrepancy: Shipment date on B/L (2023-10-16) is after the latest shipment date in L/C (2023-10-15).) |
| **46** | 제3자 지급 (Payment to 3rd Party) 미신고 | 외국환거래법 제16조 | 외국환 결제 절차 위반 (은행 거절) | 외국환거래규정 | **invoice**: AI Noted Discrepancy (BL date (Oct 16) is after latest shipment date (Oct 15) per L/C.) |
| **47** | 일방적 해지권 부여 (One-sided Termination) | 약관법 제9조 | 신의성실 원칙 위반 및 해지 무효 | 민법 제2조 | **invoice**: AI Noted Discrepancy (B/L date (2024-06-16) is after latest shipment date (2024-06-15)) |
| **48** | 물품의 본질적 적합성 면책 (As-is Clause) | CISG Art. 35 | 매수인의 본질적 계약 목적 달성 불가 | CISG Art. 25 | **invoice**: AI Noted Discrepancy (B/L Date 2024-06-16 exceeds latest shipment date 2024-06-15; Potential for L/C rejection.) |
| **49** | 중고물품의 신품 오인 표시 수출 | 대외무역법 제39조 | 원산지/품질 표시 위반 형사 처벌 | 대외무역법 제53조의2 | **invoice**: AI Noted Discrepancy (CRITICAL: Shipment date 2023-10-16 exceeds latest shipment date 2023-10-15 defined in L/C.) |
| **50** | 보증서 발행 전 선수금(Advance) 지급 강제 | URDG 758 | 회수 불능 리스크 및 계약 이행 담보 부재 | 상법 | **invoice**: AI Noted Discrepancy (Intentional Discrepancy: Shipping date 2023-11-22 is past the L/C latest shipment date of 2023-11-20.) |
| **51** | EXW 조건에서 매도인의 수출 통관 대행 | Incoterms 2020 (EXW) | 수출자 명의 불일치 및 관세 환급 불가 | Incoterms 2020 A6 | **invoice**: AI Noted Discrepancy (Invoice total exceeds L/C amount by $500. Shipment date 2024-06-21 exceeds L/C latest shipment date of 2024-06-20.) |
| **52** | 계약 해제 후 원상회복 범위 제한 | CISG Art. 81 | 손해액 산정 시 기수행 비용 보전 불가 | CISG Art. 74 | **invoice**: AI Noted Discrepancy (B/L date exceeds L/C latest shipment date by 1 day.) |
| **53** | 덤핑 가격 설정 및 수출 실적 조작 | 공정거래법 제45조 | 반덤핑 관세 부과 및 부정 수출죄 | 관세법 / 대외무역법 | - |
| **54** | 증여성 무상 거래에 대한 수입 신고 누락 | 외국환거래법 제17조 | 지급수단 등의 수출입 신고 위반 | 관세법 제241조 | **invoice**: AI Noted Discrepancy (B/L date (2024-06-21) exceeds the L/C latest shipment date (2024-06-20).) |
| **55** | 부당한 전속적 관할 합의 (매도인 국가만) | 약관법 제14조 | 제소의 현저한 곤란으로 인한 조항 무효 | 민사소송법 | **invoice**: AI Noted Discrepancy (Total amount in invoice ($555,000) exceeds L/C amount ($550,000) due to internal clerical error.) |
| **56** | 가격 결정 공식 미비 (Open Price Term) | CISG Art. 14 | 계약의 성립 자체에 대한 다툼 발생 | CISG Art. 55 | **invoice**: AI Noted Discrepancy (BL date is post-shipment deadline) |
| **57** | 대리점 계약 내 타사 제품 취급 금지 강제 | 공정거래법 제45조 | 배타적 거래 강요 행위 해당 리스크 | 공정거래법 | **invoice**: AI Noted Discrepancy (B/L date (Nov 21) is after L/C Latest Shipment Date (Nov 20).) |
| **58** | CPT 조건 하에 목적지 인도 전 위험 이전 오인 | Incoterms 2020 (CPT) | 제1운송인 인도 시 위험 이전 인식 부재 | Incoterms 2020 A3 | **invoice**: AI Noted Discrepancy (B/L date 2024-06-21 exceeds L/C latest shipment date 2024-06-20.) |
| **59** | 하자 담보 기간의 불합리한 설정 (2주 등) | 상법 제69조 | 상사 매매 특칙과의 충돌 및 조항 무효 | 민법 | - |
| **60** | 유사 상표 부착 물품의 수출 합의 | 지식재산권법 | 상표권 침해 및 세관 압류 리스크 | 대외무역법 제42조 | **invoice**: AI Noted Discrepancy (B/L date exceeds L/C latest shipment date by 1 day) |
| **61** | 미신고 해외 예금 계좌를 통한 대금 수령 | 외국환거래법 제18조 | 해외 직접 투자 및 예금 거래 위반 | 외국환거래규정 | **invoice**: AI Noted Discrepancy (Intentional: Shipment date (June 27) exceeds L/C latest shipment date (June 25).) |
| **62** | 불가항력 조항에 '정부 규제' 포함 누락 | CISG Art. 79 | 수출 금지 조치 시 이행 지체 책임 발생 | UNIDROIT Art 7.1.7 | **invoice**: AI Noted Discrepancy (B/L date (2024-07-02) exceeds L/C latest shipment date (2024-06-30)) |
| **63** | FAS 조건에서 부두 인도 시 위험 이전 지연 | Incoterms 2020 (Fas) | 본선 수령증 확보 전 사고 발생 시 분쟁 | Incoterms 2020 A3 | **invoice**: AI Noted Discrepancy (Late shipment: BL date is June 21, exceeding latest shipment date of June 20.) |
| **64** | 계약 성립 전 발생 비용의 소급 청구 | 약관법 | 부당한 비용 전가 행위 무효 | 공정거래법 | **invoice**: AI Noted Discrepancy (B/L shipped date 2023-11-16 exceeds latest shipment date 2023-11-15 per L/C.) |
| **65** | 계약 물품 외 부품 강매 (Tying) | 공정거래법 제45조 | 끼워팔기 등 불공정 거래 행위 | 독점규제법 | **invoice**: AI Noted Discrepancy (B/L date (Oct 16) is after latest shipment date (Oct 15). Potential L/C discrepancy.) |
| **66** | 해제 시 계약금 전액 몰수 (Penalty Clause) | 민법 제398조 | 손해배상액 예정의 과다 감액 대상 | 약관법 제8조 | **invoice**: AI Noted Discrepancy (Intentional Discrepancy: Shipping date 2024-07-02 exceeds latest shipment date 2024-06-30) |
| **67** | DAP 조건에서 매도인의 양하(Unloading) 거부 | Incoterms 2020 (DAP) | 양하 비용 및 위험 분담 지점 마찰 | Incoterms 2020 A3 | **invoice**: AI Noted Discrepancy (Shipment date 2023-10-16 exceeds L/C deadline 2023-10-15) |
| **68** | 이행 지체에 대한 고의/중과실 면책 특약 | 약관법 제7조 | 법률상 허용되지 않는 면책 범위 설정 | 민법 제391조 | **invoice**: AI Noted Discrepancy (Discrepancy: Shipping date 2024-07-21 exceeds L/C latest shipment date of 2024-07-20.) |
| **69** | 원산지 증명서(C/O) 대리 발급 및 허위 기재 | FTA 특례법 | 관세 포탈 및 원산지 규정 위반 | 대외무역법 제37조 | - |
| **70** | 거주자 간 외화 표시 거래의 원화 지급 거부 | 외국환거래법 | 국내 결제 원칙 위반 가능성 | 외국환거래규정 | - |
| **71** | 인도 전 대금 선입금 요구 (L/C 미사용 시) | CISG Art. 58 | 동시이행 항변권 행사의 법적 제한 | 민법 제536조 | **invoice**: AI Noted Discrepancy (B/L date (2024-06-16) exceeds L/C latest shipment date (2024-06-15).) |
| **72** | 무역 서류의 5년 미만 보관 규정 | 대외무역법 제22조 | 법정 서류 보존 의무 위반 과태료 | 대외무역법 제59조 | **invoice**: AI Noted Discrepancy (Intentional discrepancy: Invoice amount $50,005 exceeds L/C amount $50,000.) |
| **73** | CFR 조건 하에 해상 보험 가입 의무 전가 | Incoterms 2020 (CFR) | 보험 부보 주체 오인으로 인한 무보험 사고 | Incoterms 2020 B5 | - |
| **74** | PL(제조물 책임) 사고 시 매수인 전액 부담 | 제조물책임법 | 강행규정 위반 및 구상권 제한 무효 | 약관법 제6조 | **invoice**: AI Noted Discrepancy (Intentional Discrepancy: Invoice total $49,990 vs L/C amount $50,000.) |
| **75** | 외화 획득용 시설 기재의 상업적 매각 | 대외무역법 | 사후 관리 의무 위반 및 관세 추징 | 대외무역법 제16조 | - |
| **76** | 신용장 미개설 시 계약 자동 해제 조항 | CISG Art. 25 | 해제 통지 의무 위반 및 이행 최고 결여 | CISG Art. 47 | **invoice**: AI Noted Discrepancy (Shipment date 2023-10-31 exceeds L/C latest shipment date 2023-10-30) |
| **77** | CIP 조건에서 최소 보험금(110%) 미부합 | Incoterms 2020 (CIP) | ICC(A) 조건 미충족 및 신용장 불일치 | Incoterms 2020 A5 | **invoice**: AI Noted Discrepancy (Risk: Insurance certificate provided covers only 100% of invoice value; ICC (C) condition used instead of required ICC (A).) |
| **78** | 인도 기한 전 조기 인도(Early Delivery) 강요 | CISG Art. 52 | 매수인의 보관 비용 발생 및 수령 거절 | CISG Art. 86 | **invoice**: AI Noted Discrepancy (Seller shipped early, violating the restrictive L/C condition requiring post-Nov 1st shipment.) |
| **79** | 허위 수출 실적을 기반으로 한 무역 금융 수혜 | 대외무역법 제30조 | 무역 금융 사기 및 수출 실적 취소 | 형법 (사기) | **invoice**: AI Noted Discrepancy (CRITICAL: The B/L date (2024-06-16) exceeds the latest shipment date allowed in L/C (2024-06-15). Late shipment detected.) |
| **80** | 다자간 상계(Netting) 계약 시 당국 미신고 | 외국환거래법 제16조 | 중앙은행 보고 의무 위반 | 외국환거래규정 | - |
| **81** | 거래 상대방의 경영진 임명권 개입 | 공정거래법 | 거래상 지위 남용 및 경영 간섭 | 독점규제법 | **invoice**: AI Noted Discrepancy (B/L shipped date 2023-10-18 exceeds L/C latest shipment date 2023-10-15.) |
| **82** | 중재 합의 시 중재지(Seat)와 기관 불일치 | 중재법 제21조 | 중재 판정의 집행 불능 및 효력 다툼 | NYC 1958 | **invoice**: AI Noted Discrepancy (B/L date 2024-06-16 is 1 day past L/C latest shipment date) |
| **83** | DPU 조건 시 매수인의 양하 장소 지정 지연 | Incoterms 2020 (DPU) | 인도의 불능에 따른 지체 상금 발생 | Incoterms 2020 B3 | **invoice**: AI Noted Discrepancy (B/L date Oct 16 exceeds L/C latest shipment date Oct 15) |
| **84** | 대체물 인도 청구권의 부당한 포기 강제 | CISG Art. 46 | 계약 위반에 대한 매수인의 구제 수단 봉쇄 | 약관법 | - |
| **85** | 전략물자 판정 전 수출 계약 이행 완료 | 대외무역법 제20조 | 사전 판정 의무 위반 및 수출 금지 | 대외무역법 제53조 | **invoice**: AI Noted Discrepancy (SHIPMENT DATE 2023-10-16 EXCEEDS L/C LATEST SHIPMENT DATE OF 2023-10-15) |
| **86** | 영업비밀 보호를 이유로 한 장부 검사 거부 | 상법 / 공정거래법 | 대리점법상 실태 조사 방해 행위 | 공정거래법 | **invoice**: AI Noted Discrepancy (Late shipment: BL date March 16th exceeds L/C latest shipment date March 15th.) |
| **87** | B/L 기재 사항과 실제 물품의 수량 차이 | 상법 제854조 | 운송인에 대한 청구권 소멸 및 보험 보상 불가 | UCP 600 Art. 14 | **invoice**: AI Noted Discrepancy (Mismatch with B/L qty) |
| **88** | CFR 조건에서 적재 후 사고 발생 시 환불 요구 | Incoterms 2020 (CFR) | 위험 이전 법리 오해에 따른 부당 청구 | CISG Art. 67 | **invoice**: AI Noted Discrepancy (Missing internal shipment stamp for verification) |
| **89** | 중대한 위반(Fundamental Breach) 정의 제한 | CISG Art. 25 | 계약 해제권 행사의 자의적 차단 | CISG Art. 49 | **invoice**: AI Noted Discrepancy (Late shipment: B/L dated 2024-04-16 exceeds L/C deadline of 2024-04-15.) |
| **90** | 수입 물품 가격의 인위적 고가 신고 | 관세법 | 외화 도피 및 관세 포탈 혐의 | 외국환거래법 제29조 | **invoice**: AI Noted Discrepancy (CRITICAL DISCREPANCY: Invoice unit prices are double the contract value. Indicates potential capital flight/over-invoicing.) |
| **91** | 예고 없는 계약 갱신 거절 (장기 거래 시) | 공정거래법 | 거래 거절 및 신뢰 원칙 위반 | 민법 | **invoice**: AI Noted Discrepancy (B/L date 2023-10-22 exceeds L/C latest shipment date 2023-10-20. L/C non-compliance noted.) |
| **92** | 매수인의 하자 통지 기간을 '수령 즉시'로 제한 | 약관법 | 사회 통념상 불가능한 기간 설정 무효 | CISG Art. 39 | **invoice**: AI Noted Discrepancy (Invoice reflects shipment date of Oct 15, but B/L shows Oct 16 due to port delay.) |
| **93** | FOB 조건에서 선박 미지정 시 자동 대금 청구 | Incoterms 2020 (FOB) | 인도 의무 미이행 상태에서의 채권 발생 분쟁 | Incoterms 2020 A3 | **invoice**: AI Noted Discrepancy (B/L date (July 16) is after L/C latest shipment date (July 15). Late shipment discrepancy.) |
| **94** | 부수적 채무 위반 시 전체 계약 해제권 행사 | CISG Art. 25 | 해제권 남용 및 손해배상 역청구 리스크 | 민법 제2조 | - |
| **95** | 통합공고상 수입 제한 품목의 우회 수입 합의 | 대외무역법 제12조 | 부정 수입 및 법령 회피 행위 | 관세법 | - |
| **96** | 특수관계인 간 부당 저가 수출 | 공정거래법 제45조 | 부당 지원 행위 및 세무조사 리스크 | 법인세법 (부당행위계산) | - |
| **97** | 보험금 청구권의 제3자 양도 금지 특약 | 상법 | 상업적 채권 유동화 저해 및 공정성 결여 | 약관법 | **invoice**: AI Noted Discrepancy (B/L date 2023-10-16 is past latest shipment date 2023-10-15. Discrepancy observed.) |
| **98** | CIF 조건 시 목적지 도착 전 대금 지급 거절 | Incoterms 2020 (CIF) | 서류 상환 방식(CAD) 등 결제 조건 위반 | UCP 600 | **invoice**: AI Noted Discrepancy (B/L date exceeds latest shipment date by 1 day (Stale shipment).) |
| **99** | 무상 보증 기간 내 부품비 별도 청구 | 약관법 | 보증 서비스의 실질적 무력화 | CISG Art. 35 | **invoice**: AI Noted Discrepancy (Invoice amount exceeds L/C total by 50 USD due to undocumented 'service fee'.) |
| **100** | 미신고 가상자산을 이용한 무역 대금 결제 | 외국환거래법 | 지급 수단 지정 위반 및 자금세탁 의심 | 특정금융정보법 | **invoice**: AI Noted Discrepancy (B/L date 2024-06-16 exceeds latest shipment date 2024-06-15) |

---

## 3. 활용 가이드
1. **정합성 테스트**: 각 시나리오의 `master.json`과 실제 서류 간의 텍스트 불일치를 AI가 탐지하는지 확인.
2. **법률 자문 테스트**: 에이전트가 단순 오타를 넘어 "이 조항은 강행규정 위반입니다"와 같은 법률적 해석을 내놓는지 검증.
3. **배치 처리**: 노트북의 `batch_generate_scenarios` 함수를 통해 이 목록 전체를 자동 생성할 수 있습니다.
