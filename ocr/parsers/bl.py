"""
BillOfLading 파서 — 선하증권 + 항공운송장.

운송 서류는 운송사별 양식 차이 많지만 핵심 필드는 공통:
  - B/L (or AWB) Number
  - Shipper / Consignee / Notify Party
  - Vessel / Voyage / Flight
  - Port of Loading / Discharge (또는 공항)
  - Place of Receipt / Delivery
  - Container / Package / Weight / Measurement
  - Freight Terms (Prepaid / Collect)
  - Issue Date / Place
"""
from __future__ import annotations
import re
from .base import BaseParser, ParseResult


# ────────────────────────────────────────────────────────────
# 핵심 필드 정규식
# ────────────────────────────────────────────────────────────
PATTERNS = {
    # 역방향 먼저 (OCR 표 구조), 정방향 fallback
    'bl_number': [
        # 역방향
        re.compile(r'([A-Z]{3,4}\d{6,12}|[A-Z]{2,}\d{5,}[A-Z0-9]*)\s*\n\s*(?:Bill\s*of\s*Lading|B/?L)\s*(?:No\.?|Number)', re.IGNORECASE),
        re.compile(r'Bill\s*of\s*Lading\s*(?:No\.?|Number)\s*[:\.]?\s*([A-Z]{3,4}\d{6,12}|[A-Z0-9\-/]{6,30})', re.IGNORECASE),
        re.compile(r'B/?L\s*(?:No\.?|Number)\s*[:\.]?\s*([A-Z]{3,4}\d{6,12}|[A-Z0-9\-/]{6,30})', re.IGNORECASE),
        re.compile(r'(?:선하증권|선화증권)\s*번호\s*[:\.]?\s*([A-Z0-9\-/]{3,30})'),
    ],
    'awb_number': [
        # 역방향 (AWB 번호 포맷 특정)
        re.compile(r'(\d{3}-\d{7,8})\s*\n\s*(?:Air\s*Waybill|AWB)\s*(?:No\.?|Number)', re.IGNORECASE),
        re.compile(r'Air\s*Waybill\s*(?:No\.?|Number)\s*[:\.]?\s*(\d{3}-?\d{7,8})', re.IGNORECASE),
        re.compile(r'AWB\s*(?:No\.?|Number)\s*[:\.]?\s*(\d{3}-?\d{7,8})', re.IGNORECASE),
        re.compile(r'(?:항공운송장|항공화물운송장)\s*번호\s*[:\.]?\s*([A-Z0-9\-/]{3,20})'),
    ],
    'booking_no': [
        re.compile(r'([A-Z]{2,4}\d{4,10})\s*\n\s*Booking\s*(?:No\.?|Number|Ref\.?)', re.IGNORECASE),
        re.compile(r'Booking\s*(?:No\.?|Number|Ref\.?)\s*[:\.]?\s*([A-Z]{2,4}\d{4,10})', re.IGNORECASE),
    ],
    'shipper': [
        # 정방향: "Shipper\n회사명" (이 부분은 OCR에서 label이 먼저 올 수도 있음 — 표 구조상 블록 섹션)
        re.compile(r'Shipper\s*[:\.]?\s*\n\s*([^\n]{5,200}(?:\n[^\n]{3,150}){0,2})', re.IGNORECASE),
        re.compile(r'Shipper\s*[:\.]\s*([^\n]{5,200})', re.IGNORECASE),
        # 역방향
        re.compile(r'([A-Z가-힣][^\n]{5,150})\s*\n[^\n]{5,150}\s*\n\s*Shipper(?!\s*Bank)', re.IGNORECASE),
        re.compile(r'(?:송하인|수출자)\s*[:\.]?\s*([^\n]{5,200})'),
    ],
    'consignee': [
        re.compile(r'Consignee\s*[:\.]?\s*\n\s*([^\n]{5,200}(?:\n[^\n]{3,150}){0,2})', re.IGNORECASE),
        re.compile(r'Consignee\s*[:\.]\s*([^\n]{5,200})', re.IGNORECASE),
        re.compile(r'([A-Z가-힣][^\n]{5,150})\s*\n[^\n]{5,150}\s*\n\s*Consignee', re.IGNORECASE),
        re.compile(r'(?:수하인|수입자)\s*[:\.]?\s*([^\n]{5,200})'),
    ],
    'notify_party': [
        re.compile(r'Notify\s*(?:Party)?\s*[:\.]?\s*\n\s*([^\n]{5,200}(?:\n[^\n]{3,150})?)', re.IGNORECASE),
        re.compile(r'(?:통지처)\s*[:\.]?\s*([^\n]{5,200})'),
    ],
    'vessel': [
        # 역방향 먼저: "VESSEL NAME / 123E\nVessel / Voyage No."
        re.compile(r'([A-Z][A-Z\s]{3,40}\s*/\s*[A-Z0-9]{2,8})\s*\n\s*Vessel(?:\s*/\s*Voyage)?', re.IGNORECASE),
        # 정방향 — voyage 정보 직전까지 (슬래시·탭·파이프 구분자로 끊기)
        # 'MV ANCIENT MARINER (Year Built: 2002) / EG-001W' → 'MV ANCIENT MARINER (Year Built: 2002)'
        re.compile(r'(?:Vessel|Ocean\s*Vessel|선박명)\s*(?:/\s*Voyage\s*No\.?)?\s*[:\.]?\s*([^\n\t|]+?)(?=\s*/\s*[A-Z0-9]{2,8}|\s*\t|\s*\||\s*\n|\s*$)', re.IGNORECASE),
        re.compile(r'(?:Vessel|Ocean\s*Vessel|선박명)\s*(?:/\s*Voyage\s*No\.?)?\s*[:\.]?\s*([^\n]{3,80})', re.IGNORECASE),
    ],
    'voyage': [
        re.compile(r'(?:Voyage|Voy\.?)\s*(?:No\.?)?\s*[:\.]?\s*([A-Z0-9\-]{2,20})', re.IGNORECASE),
        re.compile(r'(?:항해번호)\s*[:\.]?\s*([A-Z0-9\-]{1,20})'),
    ],
    'flight_no': [
        re.compile(r'([A-Z]{2}\d{2,4})\s*\n\s*Flight\s*(?:No\.?|Number)', re.IGNORECASE),
        re.compile(r'Flight\s*(?:No\.?|Number)\s*[:\.]?\s*([A-Z]{2}\d{2,4})', re.IGNORECASE),
    ],
    'port_of_loading': [
        # 역방향 먼저 — 표 형식(탭/파이프 구분) 대응 추가
        re.compile(r'([^\n\t|]{3,80}?)\s*\n\s*Port\s*of\s*Loading', re.IGNORECASE),
        # 정방향 — 라벨 뒤 탭/파이프/줄바꿈 직전까지 (탐욕 방지)
        re.compile(r'Port\s*of\s*Loading\s*[:\.]?\s*([^\n\t|]{3,80}?)(?=\s*(?:\t|\||\n|$|VESSEL|VOYAGE|Port\s*of\s*Discharge))', re.IGNORECASE),
        re.compile(r'Port\s*of\s*Loading\s*[:\.]?\s*([^\n\t|]{3,80})', re.IGNORECASE),
        re.compile(r'(?:선적항)\s*[:\.]?\s*([^\n\t|]{3,80})'),
    ],
    'port_of_discharge': [
        re.compile(r'([^\n\t|]{3,80}?)\s*\n\s*Port\s*of\s*Discharge', re.IGNORECASE),
        re.compile(r'Port\s*of\s*(?:Discharge|Destination)\s*[:\.]?\s*([^\n\t|]{3,80}?)(?=\s*(?:\t|\||\n|$|VESSEL|VOYAGE|Place\s*of\s*Delivery))', re.IGNORECASE),
        re.compile(r'Port\s*of\s*(?:Discharge|Destination)\s*[:\.]?\s*([^\n\t|]{3,80})', re.IGNORECASE),
        re.compile(r'(?:도착항|양륙항|목적항)\s*[:\.]?\s*([^\n\t|]{3,80})'),
    ],
    'place_of_receipt': [
        re.compile(r'([^\n\t|]{3,80}?)\s*\n\s*Place\s*of\s*Receipt', re.IGNORECASE),
        re.compile(r'Place\s*of\s*Receipt\s*[:\.]?\s*([^\n\t|]{3,80}?)(?=\s*(?:\t|\||\n|$|Port|Place\s*of\s*Delivery))', re.IGNORECASE),
        re.compile(r'Place\s*of\s*Receipt\s*[:\.]?\s*([^\n\t|]{3,80})', re.IGNORECASE),
        re.compile(r'(?:인수지|수탁지)\s*[:\.]?\s*([^\n\t|]{3,80})'),
    ],
    'place_of_delivery': [
        re.compile(r'([^\n\t|]{3,80}?)\s*\n\s*Place\s*of\s*Delivery', re.IGNORECASE),
        re.compile(r'Place\s*of\s*Delivery\s*[:\.]?\s*([^\n\t|]{3,80}?)(?=\s*(?:\t|\||\n|$|VESSEL|VOYAGE|Description))', re.IGNORECASE),
        re.compile(r'Place\s*of\s*Delivery\s*[:\.]?\s*([^\n\t|]{3,80})', re.IGNORECASE),
        re.compile(r'(?:배송지|인도지)\s*[:\.]?\s*([^\n\t|]{3,80})'),
    ],
    'airport_of_departure': [
        re.compile(r'([^\n]{3,80})\s*\n\s*Airport\s*of\s*Departure', re.IGNORECASE),
        re.compile(r'Airport\s*of\s*Departure\s*[:\.]?\s*([^\n]{3,80})', re.IGNORECASE),
    ],
    'airport_of_destination': [
        re.compile(r'([^\n]{3,80})\s*\n\s*Airport\s*of\s*Destination', re.IGNORECASE),
        re.compile(r'Airport\s*of\s*Destination\s*[:\.]?\s*([^\n]{3,80})', re.IGNORECASE),
    ],
    'gross_weight': [
        re.compile(r'([0-9,\.]+)\s*(KGS?|LBS?|TONS?)\s*\n\s*(?:Gross\s*Weight|Total\s*Gross)', re.IGNORECASE),
        re.compile(r'(?:Gross\s*Weight|Total\s*Gross\s*Weight|G\.W\.|총중량)\s*[:\.]?\s*([0-9,\.]+)\s*(KGS?|LBS?|TONS?)', re.IGNORECASE),
    ],
    'measurement': [
        re.compile(r'([0-9,\.]+)\s*(CBM|M3|CFT)\s*\n\s*(?:Measurement|Total\s*Measurement)', re.IGNORECASE),
        re.compile(r'(?:Measurement|Total\s*Measurement|CBM|용적)\s*[:\.]?\s*([0-9,\.]+)\s*(M3|CBM|CFT)?', re.IGNORECASE),
    ],
    'freight_terms': [
        re.compile(r'(FREIGHT\s*PREPAID|FREIGHT\s*COLLECT)\s*\n\s*Freight\s*(?:Terms)?', re.IGNORECASE),
        re.compile(r'Freight\s*(?:Terms)?\s*[:\.]?\s*(Prepaid|Collect|FREIGHT\s*PREPAID|FREIGHT\s*COLLECT)', re.IGNORECASE),
    ],
    'issue_date': [
        re.compile(r'(\d{4}[-./]\d{1,2}[-./]\d{1,2})\s*\n\s*(?:Date\s*of\s*Issue|Issue\s*Date)', re.IGNORECASE),
        re.compile(r'(?:Date\s*of\s*Issue|Issue\s*Date|Shipped\s*on\s*Board\s*Date)\s*[:\.]?\s*(\d{4}[-./]\d{1,2}[-./]\d{1,2})', re.IGNORECASE),
    ],
    'issue_place': [
        re.compile(r'([^\n]{3,80})\s*\n\s*(?:Place\s*of\s*Issue|Issue\s*Place)', re.IGNORECASE),
        re.compile(r'(?:Place\s*of\s*Issue|Issue\s*Place)\s*[:\.]?\s*([^\n]{3,80})', re.IGNORECASE),
    ],
}

# 컨테이너 번호 / 씰 번호
CONTAINER_PAT = re.compile(
    r'([A-Z]{4}\d{7})',  # 표준 컨테이너 번호: 4영문 + 7숫자
)


# BL 값 블랙리스트 (라벨·섹션 헤더)
BL_VALUE_BLACKLIST = {
    'port of loading', 'port of discharge', 'place of receipt',
    'place of delivery', 'airport of departure', 'airport of destination',
    'bill of lading no.', 'bill of lading', 'booking no.', 'booking ref.',
    'shipper', 'consignee', 'notify party', 'notify', 'carrier',
    'vessel', 'voyage', 'voyage no.', 'vessel / voyage no.',
    'air waybill no.', 'flight no.', 'freight terms',
    'gross weight', 'total gross weight', 'measurement', 'total measurement',
    'total packages', 'number of pieces', 'chargeable weight',
    'export references', 'particulars furnished by shipper',
    'nature and quantity of goods',
    'date of issue', 'place of issue', 'issue date',
    'ref', 'ref:',
}


def _is_blacklisted(value: str) -> bool:
    if not value:
        return True
    v = value.strip().lower()
    v_clean = re.sub(r'[:\.\-\s]+$', '', v).strip()
    if v_clean in BL_VALUE_BLACKLIST:
        return True
    if len(v_clean) < 3:
        return True
    if any(v_clean.startswith(prefix) for prefix in [
        'port of', 'place of', 'airport of', 'bill of lading',
        'air waybill', 'vessel', 'voyage', 'shipper', 'consignee',
        'notify', 'booking', 'date of', 'particulars', 'nature and',
        'export references',
    ]):
        return True
    return False


def _extract_fields(text: str) -> dict:
    found = {}
    for field_name, patterns in PATTERNS.items():
        for pat in patterns:
            for m in pat.finditer(text):
                if m.lastindex == 2:
                    v = m.group(1).strip()
                    if _is_blacklisted(v):
                        continue
                    found[field_name] = {
                        'value': v,
                        'unit': m.group(2),
                        'raw': m.group(0),
                    }
                    break
                else:
                    v = m.group(1).strip() if m.lastindex else m.group(0).strip()
                    if _is_blacklisted(v):
                        continue
                    found[field_name] = {
                        'value': v,
                        'raw': m.group(0),
                    }
                    break
            if field_name in found:
                break
    return found


# ────────────────────────────────────────────────────────────────────
# 4/30 — 합성 PDF 양식 보완 (콜론 없는 라벨 + 슬래시 결합 + 번호 prefix)
# ────────────────────────────────────────────────────────────────────
# 양식 1 (sc1): SHIPPER:\t...\tCONSIGNEE:... (탭 구분), VESSEL / VOYAGE: V / VID
# 양식 2 (sc2_10·13): 'Shipper NAME B/L No' (콜론 없음, 한 줄 압축)
# 양식 3 (sc2_11·12): '1. SHIPPER NAME\t1. SHIPPER NAME\t...' (번호 + 반복 탭)

def _clean_bl_value(s: str) -> str:
    if not s:
        return s
    s = s.strip().rstrip(',').rstrip('.').strip()
    # tab/pipe trailing
    s = re.sub(r'\s*[\t|]\s*.*$', '', s)
    return s


SYNTH_BL_PATTERNS = {
    'shipper': [
        # 양식 1: 'SHIPPER: NAME ... <tab> CONSIGNEE:' (콜론 + 탭)
        re.compile(
            r'\bSHIPPER\s*:\s+([A-Z][A-Z0-9\s\.,&\-]{4,150}?)(?=\s*\t|\s+CONSIGNEE|\s*\n)',
            re.IGNORECASE,
        ),
        # 양식 2: 'Shipper NAME B/L No' (콜론 없음)
        re.compile(
            r'\bShipper\s+([A-Z][A-Z0-9\s\.,&\-]{4,80}?)\s+(?=B\s*/?\s*L\s*No|Consignee|Vessel|Notify|$)',
            re.IGNORECASE,
        ),
        # 양식 3: '1. SHIPPER NAME\t' (번호 + 탭)
        re.compile(
            r'(?:\d+\.\s+)?SHIPPER\s+([A-Z][A-Z0-9\s\.,&\-]{4,80}?)(?=\s*\t|\s*$|\s+BILL\s+OF\s+LADING)',
            re.IGNORECASE,
        ),
    ],
    'consignee': [
        # 양식 1: 'CONSIGNEE: NAME ... <tab>'
        re.compile(
            r'\bCONSIGNEE\s*:\s+([A-Z][A-Z0-9\s\.,&\-]{4,150}?)(?=\s*\t|\s*\n|\s+NOTIFY)',
            re.IGNORECASE,
        ),
        # 양식 2: 'Consignee NAME Vessel' (콜론 없음)
        re.compile(
            r'\bConsignee\s+([A-Z][A-Z0-9\s\.,&\-]{4,80}?)\s+(?=Vessel|Notify|Container|Final|$)',
            re.IGNORECASE,
        ),
        # 양식 3: '2. CONSIGNEE NAME\t'
        re.compile(
            r'(?:\d+\.\s+)?CONSIGNEE\s+([A-Z][A-Z0-9\s\.,&\-]{4,80}?)(?=\s*\t|\s*$|\s+BILL\s+OF\s+LADING)',
            re.IGNORECASE,
        ),
    ],
    'bl_number': [
        # 양식 3: 'BILL OF LADING B/L NO. ID' (콜론 없음, 점만)
        re.compile(
            r'BILL\s+OF\s+LADING\s+B\s*/?\s*L\s*NO\.?\s+([A-Z][A-Z0-9\-]{3,30})',
            re.IGNORECASE,
        ),
    ],
    # vessel + voyage 슬래시 결합 — 두 그룹 (vessel, voyage)
    'vessel_voyage_combined': [
        # 양식 1: 'VESSEL / VOYAGE: COSCO Pioneer / CS240815' (콜론 + 옵셔널 NO)
        re.compile(
            r'VESSEL\s*/\s*VOYAGE\s*(?:NO\.?)?\s*[:.]?\s+([A-Z][A-Z0-9\s\-]+?)\s*/\s*([A-Z0-9\-]{2,15})(?=\s|\t|$|\n)',
            re.IGNORECASE,
        ),
        # 양식 2: 'Vessel / Voyage SKY TIARA / 2404S' (콜론 없음)
        re.compile(
            r'Vessel\s*/\s*Voyage\s+([A-Z][A-Z0-9\s\-]+?)\s*/\s*([A-Z0-9\-]{2,15})(?=\s+Notify|\s+Container|\s+Marks|\s*$|\s*\n|\s+PORT|\s+Final)',
            re.IGNORECASE,
        ),
        # 양식 4 (KST sc2_5): 'VESSEL NAME V.VOY\t' (V. prefix 줄임말)
        re.compile(
            r'VESSEL\s+([A-Z][A-Z0-9\s\-]+?)\s+V\.([A-Z0-9\-]{2,12})(?=\s|\t|$|\n)',
            re.IGNORECASE,
        ),
    ],
    # 표 형식 port (양식 1) — `Port of Loading\tPort of Discharge\t...\nVAL1\tVAL2\t...`
    'port_of_loading': [
        re.compile(
            r'Port\s+of\s+Loading\s*\t\s*Port\s+of\s+Discharge.*?\n\s*([^\t\n]+?)\s*\t',
            re.IGNORECASE | re.DOTALL,
        ),
        # 양식 3: 'PORT OF LOADING Busan Port\tVESSEL...' (탭 구분, mixed case 허용)
        re.compile(
            r'PORT\s+OF\s+LOADING\s+([A-Za-z][A-Za-z0-9\s\.,\-]+?)(?=\s*\t|\s+(?:PORT\s+OF\s+DISCHARGE|VESSEL|VOYAGE|FINAL|FREIGHT|\d+\.\s+|MARKS|$))',
            re.IGNORECASE,
        ),
        # 'PORT OF LOADING:\tNAME\t' (콜론 + 탭)
        re.compile(
            r'PORT\s+OF\s+LOADING\s*[:.]?\s*\t\s*([^\t\n]+?)\s*\t',
            re.IGNORECASE,
        ),
        # 양식 4 (sc2_5 KST): 'POL POHANG PORT, KOREA\t' (줄임말)
        re.compile(
            r'\bPOL\s+([A-Za-z][A-Za-z0-9\s\.,\-]+?)(?=\s*\t|\s+POD|\s*\n|\s*$)',
        ),
    ],
    'port_of_discharge': [
        re.compile(
            r'Port\s+of\s+Loading\s*\t\s*Port\s+of\s+Discharge.*?\n\s*[^\t\n]+\s*\t\s*([^\t\n]+?)\s*\t',
            re.IGNORECASE | re.DOTALL,
        ),
        # 양식 3: 'PORT OF DISCHARGE Port of Ambarli ...' (mixed case 허용 + 다음 라벨 lookahead)
        re.compile(
            r'PORT\s+OF\s+DISCHARGE\s+([A-Za-z][A-Za-z0-9\s\.,\-]+?)(?=\s*\t|\s+(?:PLACE\s+OF|FINAL|FREIGHT|\d+\.\s+|MARKS|$))',
            re.IGNORECASE,
        ),
        # 양식 4 (sc2_5 KST): 'POD BUENOS AIRES PORT, ARGENTINA' (줄임말)
        re.compile(
            r'\bPOD\s+([A-Za-z][A-Za-z0-9\s\.,\-]+?)(?=\s*\t|\s*\n|\s+FREIGHT|\s+SHIPPED|\s*$)',
        ),
    ],
}


def _extract_synth_bl_fields(text: str) -> dict:
    """합성 PDF 양식 BL 보완 추출. 빠진 필드만 채움."""
    out = {}
    for field_name, pats in SYNTH_BL_PATTERNS.items():
        for pat in pats:
            for m in pat.finditer(text):
                if field_name == 'vessel_voyage_combined':
                    vessel_val = _clean_bl_value(m.group(1))
                    voyage_val = _clean_bl_value(m.group(2))
                    if vessel_val and not _is_blacklisted(vessel_val):
                        out.setdefault('vessel', {'value': vessel_val, 'raw': m.group(0)})
                    if voyage_val and not _is_blacklisted(voyage_val):
                        out.setdefault('voyage', {'value': voyage_val, 'raw': m.group(0)})
                    break
                else:
                    val = _clean_bl_value(m.group(1))
                    if not val or _is_blacklisted(val):
                        continue
                    out.setdefault(field_name, {'value': val, 'raw': m.group(0)})
                    break
            if field_name in out or (field_name == 'vessel_voyage_combined' and ('vessel' in out and 'voyage' in out)):
                break
    return out


def _extract_containers(text: str) -> list[str]:
    """표준 컨테이너 번호 (예: MAEU1234567) 추출."""
    matches = CONTAINER_PAT.findall(text)
    # 중복 제거 순서 유지
    seen = set()
    unique = []
    for c in matches:
        if c not in seen:
            seen.add(c)
            unique.append(c)
    return unique


def _is_air_waybill(text: str) -> bool:
    """Air Waybill인지 판별."""
    text_upper = text.upper()
    return (
        'AIR WAYBILL' in text_upper
        or 'AWB' in text_upper
        or 'FLIGHT' in text_upper
        or '항공운송장' in text
        or '항공화물' in text
    )


# ────────────────────────────────────────────────────────────
class BillOfLadingParser(BaseParser):
    """선하증권 / 항공운송장 파서."""
    DOCUMENT_TYPE = 'BillOfLading'

    def _extract_type_specific(self, text: str, ocr_result: dict,
                                result: ParseResult) -> None:
        is_awb = _is_air_waybill(text)
        result.type_specific['is_air_waybill'] = is_awb
        result.type_specific['transport_mode'] = 'air' if is_awb else 'sea'

        fields = _extract_fields(text)

        # 4/30 — 합성 PDF 양식 보완 (콜론 없는 라벨 + 슬래시 결합 + 번호 prefix)
        # vessel/voyage 는 기존 패턴이 노이즈 흡수해서 잘못된 값 채움 → 강제 덮어쓰기
        synth = _extract_synth_bl_fields(text)
        FORCE_OVERRIDE = {'vessel', 'voyage'}
        for k, v in synth.items():
            if k in FORCE_OVERRIDE:
                fields[k] = v  # 합성 패턴이 더 정확
            else:
                fields.setdefault(k, v)

        result.type_specific['fields'] = fields

        containers = _extract_containers(text)
        result.type_specific['containers'] = containers
        result.type_specific['n_containers'] = len(containers)

        # 평탄 key_fields
        result.type_specific['key_fields'] = {
            name: data.get('value') or data.get('raw')
            for name, data in fields.items()
        }

        # warnings
        essential = ['bl_number', 'awb_number', 'shipper', 'consignee']
        has_doc_no = ('bl_number' in fields) or ('awb_number' in fields)
        has_shipper = 'shipper' in fields
        has_consignee = 'consignee' in fields

        missing = []
        if not has_doc_no:
            missing.append('BL_AWB_NUMBER')
        if not has_shipper:
            missing.append('SHIPPER')
        if not has_consignee:
            missing.append('CONSIGNEE')
        if missing:
            result.warnings.append(f'MISSING_FIELDS:{",".join(missing)}')

    def _compute_confidence(self, result: ParseResult) -> float:
        fields = result.type_specific.get('fields', {})
        n = len(fields)
        if n >= 8:
            base = 0.85
        elif n >= 5:
            base = 0.65
        elif n >= 3:
            base = 0.45
        elif n >= 1:
            base = 0.2
        else:
            base = 0.0
        if result.type_specific.get('n_containers', 0) > 0:
            base += 0.1
        return min(base, 1.0)
