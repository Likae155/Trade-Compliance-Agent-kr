import re
from typing import Dict, List, Optional, Union
from datetime import datetime

class NumericalValidator:
    """
    무역 서류 데이터의 수치 정합성을 결정론적(Deterministic)으로 검증하는 클래스.
    """
    
    @staticmethod
    def find_key_recursive(data: Union[Dict, List], target_key: str) -> Optional[any]:
        """중첩된 딕셔너리/리스트에서 키를 재귀적으로 검색 (다중 문서 지원)"""
        if isinstance(data, list):
            for item in data:
                result = NumericalValidator.find_key_recursive(item, target_key)
                if result is not None: return result
            return None
            
        if not isinstance(data, dict):
            return None

        if target_key in data:
            return data[target_key]
        
        for key, value in data.items():
            if isinstance(value, (dict, list)):
                result = NumericalValidator.find_key_recursive(value, target_key)
                if result is not None: return result
        return None

    @staticmethod
    def extract_numbers(text: str) -> List[float]:
        """텍스트에서 숫자만 추출 (금액, 퍼센트 등)"""
        if not text: return []
        clean_text = str(text).replace(',', '')
        return [float(n) for n in re.findall(r'[-+]?\d*\.\d+|\d+', clean_text)]

    @classmethod
    def check_insurance_coverage(cls, json_data: Dict) -> Dict:
        """보험 부보율 검증 (기본 110%)"""
        # 시나리오 4 등 복합 구조 대응을 위해 'insurance', 'coverage' 등을 광범위하게 검색
        insurance_data = cls.find_key_recursive(json_data, 'insurance')
        coverage = ""
        
        if isinstance(insurance_data, dict):
            coverage = insurance_data.get('coverage', '')
        elif insurance_data:
            coverage = str(insurance_data)
        else:
            # 직접 coverage 키 검색
            coverage = cls.find_key_recursive(json_data, 'coverage') or ""
        
        match = re.search(r'(\d+)%', str(coverage))
        if match:
            value = int(match.group(1))
            if value < 110:
                return {"status": "FAIL", "message": f"보험 부보율 부족: {value}% (최소 110% 필요)"}
            return {"status": "PASS", "message": f"보험 부보율 적정: {value}%"}
        
        return {"status": "UNKNOWN", "message": "보험 부보율 정보를 찾을 수 없습니다."}

    @classmethod
    def compare_amounts(cls, json_data: Dict) -> Dict:
        """LC 금액과 Invoice 금액 대조"""
        lc_amount = cls.find_key_recursive(json_data, 'lc_amount') or cls.find_key_recursive(json_data, 'amount')
        invoice_amount = cls.find_key_recursive(json_data, 'invoice_amount') or cls.find_key_recursive(json_data, 'total_amount')
        
        if not lc_amount or not invoice_amount:
            return {"status": "UNKNOWN", "message": "금액 정보(LC/Invoice)가 누락되었습니다."}
            
        try:
            lc_val = float(str(lc_amount).replace(',', ''))
            inv_val = float(str(invoice_amount).replace(',', ''))
            
            if inv_val > lc_val:
                return {"status": "FAIL", "message": f"Invoice 금액({inv_val})이 LC 금액({lc_val})을 초과합니다."}
            return {"status": "PASS", "message": f"LC/Invoice 금액 정합성 확인 ({inv_val} <= {lc_val})"}
        except ValueError:
            return {"status": "ERROR", "message": "금액 데이터 형식이 올바르지 않습니다."}

    @classmethod
    def check_dates(cls, json_data: Dict) -> Dict:
        """선적 마감일과 실제 선적일 비교 (지연 선적 탐지)"""
        dates = cls.find_key_recursive(json_data, 'dates')
        if not dates or not isinstance(dates, dict):
            return {"status": "UNKNOWN", "message": "날짜 정보를 찾을 수 없습니다."}
        
        latest_shipment = dates.get('latest_shipment_date')
        bl_date = dates.get('bl_date')
        
        if not latest_shipment or not bl_date:
            return {"status": "UNKNOWN", "message": "선적 관련 날짜가 누락되었습니다."}
            
        if bl_date > latest_shipment:
            return {"status": "FAIL", "message": f"지연 선적 발생: 선적 마감일({latest_shipment})보다 선적일({bl_date})이 늦습니다."}
        return {"status": "PASS", "message": f"선적일 적정 ({bl_date} <= {latest_shipment})"}

    @classmethod
    def get_summary(cls, json_data: Dict) -> str:
        """JSON 데이터 내의 핵심 수치들을 추출하여 요약 리포트를 생성합니다."""
        def get_val(k): return cls.find_key_recursive(json_data, k)
        
        lc_amt = get_val('lc_amount') or get_val('amount')
        inv_amt = get_val('invoice_amount') or get_val('total_amount')
        insurance = get_val('coverage') or get_val('insurance')
        incoterms = get_val('incoterms') or get_val('incoterm')
        
        summary = "### 📊 [Input Data Summary]\n"
        summary += f"- Incoterms: {incoterms}\n"
        summary += f"- L/C Amount: {lc_amt}\n"
        summary += f"- Invoice Total: {inv_amt}\n"
        summary += f"- Insurance: {insurance}\n"
        
        # 특수 조건(Special Conditions) 추출
        contract = get_val('contract')
        if isinstance(contract, dict):
            spec = contract.get('special_conditions', '')
            if spec:
                summary += f"- Special Conditions: {spec}\n"
        
        return summary

    @classmethod
    def get_master_summary(cls, json_data: Dict) -> str:
        """거래의 핵심 팩트(당사자, 물류, 금액, 날짜)를 마크다운 테이블로 요약합니다."""
        def get_val(k): return cls.find_key_recursive(json_data, k)
        
        # 당사자 정보
        exporter = cls.find_key_recursive(json_data, 'exporter')
        importer = cls.find_key_recursive(json_data, 'importer')
        exp_name = exporter.get('name') if isinstance(exporter, dict) else "미확인"
        imp_name = importer.get('name') if isinstance(importer, dict) else "미확인"
        
        # 물류 정보
        pol = cls.find_key_recursive(json_data, 'port_loading')
        pod = cls.find_key_recursive(json_data, 'port_discharge')
        pol_name = pol.get('name') if isinstance(pol, dict) else "미확인"
        pod_name = pod.get('name') if isinstance(pod, dict) else "미확인"
        
        # 핵심 수치
        incoterms = get_val('incoterms') or "미확인"
        amount = get_val('total_amount') or get_val('lc_amount') or "미확인"
        currency = get_val('currency') or "USD"
        
        # 주요 날짜
        deadline = get_val('latest_shipment_date') or get_val('shipment_deadline') or "미확인"
        actual = get_val('bl_date') or get_val('shipped_on_board_date') or "미확인"
        
        summary = "### 📋 [기본 거래 정보 요약]\n"
        summary += f"| 항목 | 내용 |\n| :--- | :--- |\n"
        summary += f"| **수출자** | {exp_name} |\n"
        summary += f"| **수입자** | {imp_name} |\n"
        summary += f"| **선적항 / 하역항** | {pol_name} / {pod_name} |\n"
        summary += f"| **거래 조건 (Incoterms)** | {incoterms} |\n"
        summary += f"| **거래 금액** | {amount} {currency} |\n"
        summary += f"| **선적 기한 / 실제 선적** | {deadline} / {actual} |\n"
        
        return summary

    @classmethod
    def check_internal_arithmetic(cls, json_data: Dict) -> Dict:
        """단일 문서 내 (수량 * 단가 = 금액) 및 (항목 합계 = 총액) 검증"""
        items = cls.find_key_recursive(json_data, 'items') or []
        total_amount_raw = cls.find_key_recursive(json_data, 'total_amount') or cls.find_key_recursive(json_data, 'amount')
        
        if not items:
            return {"status": "UNKNOWN", "message": "품목 상세 정보가 없어 산술 검증을 수행할 수 없습니다."}

        try:
            calculated_total = 0.0
            errors = []
            
            for i, item in enumerate(items):
                qty = float(str(item.get('quantity', 0)).replace(',', ''))
                unit_price = float(str(item.get('unit_price', 0)).replace(',', ''))
                item_amount = float(str(item.get('amount', 0)).replace(',', ''))
                
                # 1. 개별 항목 산술 체크 (수량 * 단가 = 금액)
                if abs((qty * unit_price) - item_amount) > 0.01:
                    errors.append(f"품목 {i+1} 산술 불일치: {qty} * {unit_price} != {item_amount}")
                
                calculated_total += item_amount

            # 2. 전체 합계 체크
            if total_amount_raw:
                total_val = float(str(total_amount_raw).replace(',', ''))
                if abs(calculated_total - total_val) > 0.01:
                    return {
                        "status": "FAIL", 
                        "message": f"총액 불일치: 상세 합계({calculated_total}) != 명시된 총액({total_val}). OCR 인식 오류(콤마 유실 등)가 의심됩니다."
                    }
            
            if errors:
                return {"status": "WARNING", "message": " / ".join(errors)}
                
            return {"status": "PASS", "message": "문서 내 수치 산술 정합성 확인 완료 (상세 합계와 총액 일치)"}
            
        except (ValueError, TypeError):
            return {"status": "ERROR", "message": "산술 검증 중 데이터 형식 오류 발생"}

    @classmethod
    def validate_all(cls, json_data: Dict) -> str:
        """결정론적 검증 결과와 데이터 요약을 합쳐서 반환"""
        results = [
            cls.check_internal_arithmetic(json_data),
            cls.check_insurance_coverage(json_data),
            cls.compare_amounts(json_data),
            cls.check_dates(json_data)
        ]
        
        # 기본 거래 정보 요약 (테이블)
        report = cls.get_master_summary(json_data) + "\n\n"
        
        report += "### 🚨 [시스템 팩트 체크 결과]\n"
        has_fail = False
        for res in results:
            if res['status'] == "FAIL":
                has_fail = True
                report += f"❌ [결함 적발] {res['message']}\n"
            elif res['status'] == "PASS":
                report += f"✅ [정상 확인] {res['message']}\n"
            else:
                report += f"⚠️ [{res['status']}] {res['message']}\n"
        
        if not has_fail:
            report += "✅ 수치 및 날짜상 명백한 하자는 발견되지 않았습니다.\n"
        
        report += "\n" + cls.get_summary(json_data)
        return report
