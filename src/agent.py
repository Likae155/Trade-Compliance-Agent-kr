"""
################################################################################
# 법률 분석 에이전트 핵심 로직 (src/agent.py)
# 
# [개발자 가이드]
# - LangGraph를 사용하여 법률 질의 응답 및 서류 분석 워크플로우를 구성합니다.
# - retrieve(검색) → validate(검증) → grade(평가) → resolve(해결) → critic(비판)
# - Fine-tuning된 Gemma4-e2b 모델을 사용하여 법리 판단을 수행합니다.
# - 서류 유형(SalesContract 등)에 따라 프롬프트 지침(INSTRUCTION_A/B)을 분기합니다.
# 
# [주의사항]
# - 워크플로우 상태 관리(AgentState)는 TypedDict로 정의되어 있으므로 수정 시 주의하십시오.
# - 실제 분석 모델은 가중치를 사용하는 외부 모듈에 의존하므로 로직 변경을 최소화하십시오.
################################################################################
"""
import json
import re
import os
import time
import logging
import sys
sys.stdout = sys.__stdout__
from datetime import datetime
from typing import List, TypedDict, Optional
from langgraph.graph import StateGraph, END
from .engine import LegalEngine
from .llm import LLMManager
from .prompts import GRADER_PROMPT, RESOLVER_PROMPT, PREP_PROMPT, INSTRUCTION_A, INSTRUCTION_B, CRITIC_PROMPT
from .validators import NumericalValidator

class AgentState(TypedDict):
    query: str
    jurisdiction: Optional[str]
    category: Optional[str]
    contract_year: Optional[int]
    documents: List[dict]
    filtered_docs: List[dict]
    confidence_level: str
    iteration: int
    resolve_count: int
    critic_feedback: Optional[str]
    first_draft: Optional[str]
    final_judgment: str
    prep_analysis: Optional[str]
    user_preferences: str
    numerical_validation: Optional[str]
    raw_json: Optional[str]
    logs: List[str]

class LegalAgent:
    def __init__(self, fast_model="gemma4-e2b-ft-gguf:latest", heavy_model="gemma4-e2b-ft-gguf:latest"):
        self.engine = LegalEngine()
        self.llm_manager = LLMManager(fast_model, heavy_model)
        self.user_prefs = self._load_user_preferences()
        self.workflow = self._create_workflow()

    def _load_user_preferences(self) -> str:
        pref_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config', 'user_preferences.md')
        if os.path.exists(pref_path):
            with open(pref_path, 'r', encoding='utf-8') as f:
                return f.read()
        return "사용자 정의 정책 없음"

    def _create_workflow(self):
        graph = StateGraph(AgentState)
        graph.add_node("retrieve", self.retrieve_node)
        graph.add_node("validate", self.validate_node)
        graph.add_node("grade", self.grade_node)
        graph.add_node("resolve", self.resolve_node)
        graph.add_node("critic", self.critic_node)
        
        graph.set_entry_point("retrieve")
        graph.add_edge("retrieve", "validate")
        graph.add_edge("validate", "grade")
        graph.add_edge("grade", "resolve")
        graph.add_edge("resolve", "critic")
        
        graph.add_conditional_edges(
            "critic",
            self.should_continue,
            {
                "continue": "resolve",
                "end": END
            }
        )
        return graph.compile()

    def retrieve_node(self, state: AgentState):
        docs = self.engine.hybrid_search(state['query'], jurisdiction=state.get('jurisdiction'))
        return {"documents": docs, "iteration": state['iteration'] + 1, "raw_json": state.get('raw_json')}

    def validate_node(self, state: AgentState):
        try:
            raw_data = state.get("raw_json")
            if raw_data:
                json_data = json.loads(raw_data) if isinstance(raw_data, str) else raw_data
                result = NumericalValidator.validate_all(json_data)
            else: result = "검증 데이터 없음"
        except: result = "수치 검증 수행 불가"
        return {"numerical_validation": result, "raw_json": state.get('raw_json')}

    def grade_node(self, state: AgentState):
        return {"filtered_docs": state['documents'][:3], "confidence_level": "High", "raw_json": state.get('raw_json')}

    def resolve_node(self, state: AgentState):
        llm = self.llm_manager.get_heavy_llm()
        context = ""
        for d in state['filtered_docs']:
            context += f"Source: {d['law_name']} (Art. {d['article_no']})\nContent: {d['content'][:1000]}\n\n"
        
        numerical_facts = state.get("numerical_validation") or "검증 데이터 없음"

        # [v10.0] Fine-tuning 지침 분기 (계약서 단독 vs 서류 간 대조)
        instruction = INSTRUCTION_B 
        try:
            raw_data = state.get("raw_json")
            if raw_data:
                parsed = json.loads(raw_data) if isinstance(raw_data, str) else raw_data
                
                found_doc_type = None
                if isinstance(parsed, list) and len(parsed) > 0:
                    found_doc_type = parsed[0].get('document_type') or parsed[0].get('data', {}).get('document_type')
                elif isinstance(parsed, dict):
                    found_doc_type = parsed.get('document_type')
                
                logging.info(f"DEBUG [resolve_node]: OCR raw doc_type: {found_doc_type}")
                
                # 강제 분기: SalesContract로 분류되면 무조건 A
                if found_doc_type and 'salescontract' in str(found_doc_type).lower():
                    instruction = INSTRUCTION_A
                    logging.info("DEBUG [resolve_node]: Forced Instruction A (SalesContract).")
                else:
                    instruction = INSTRUCTION_B
                    logging.info("DEBUG [resolve_node]: Instruction B applied (Default).")
        except Exception as e:
            logging.error(f"DEBUG [resolve_node]: Logic error: {e}")
            pass

        logging.info(f"DEBUG [resolve_node]: Final decision: {'INSTRUCTION_A' if instruction == INSTRUCTION_A else 'INSTRUCTION_B'}")
        
        # 모델 안정화를 위한 대기
        time.sleep(2)

        # 팩트 우선 원칙 적용된 프롬프트 실행
        res = llm.invoke(RESOLVER_PROMPT.format(
            instruction=instruction,
            query=state['query'], 
            context=context,
            numerical_facts=numerical_facts,
            user_prefs=state.get('user_preferences', '')
        ))
        return {"final_judgment": res.content, "resolve_count": state['resolve_count'] + 1}

    def critic_node(self, state: AgentState):
        """[v10.0] 작성된 보고서를 자가 검증하여 품질을 보증합니다."""
        llm = self.llm_manager.get_heavy_llm()
        context = ""
        for d in state['filtered_docs']:
            context += f"Source: {d['law_name']} (Art. {d['article_no']})\n"

        res = llm.invoke(CRITIC_PROMPT.format(
            query=state['query'],
            judgment=state['final_judgment'],
            context=context
        ))
        
        content = res.content
        if "PASS" in content.upper():
            return {"critic_feedback": "PASS"}
        else:
            # 수정 지시사항 추출
            feedback = content.split("수정 지시:")[-1].strip() if "수정 지시:" in content else content
            return {"critic_feedback": feedback}

    def should_continue(self, state: AgentState):
        """비판 결과에 따라 루프 지속 여부 결정 (최대 2회)"""
        if state.get("critic_feedback") == "PASS" or state['resolve_count'] >= 2:
            return "end"
        return "continue"

    def run(self, query: str, jurisdiction: str = None, raw_json: str = None, user_instruction: str = None):
        combined_prefs = self.user_prefs
        if user_instruction:
            combined_prefs = f"### [이번 분석 특별 지시]\n{user_instruction}\n\n" + combined_prefs
            
        initial_state = {
            "query": query, "jurisdiction": jurisdiction, "category": None,
            "contract_year": None, "documents": [], "filtered_docs": [],
            "confidence_level": "None", "iteration": 0, "resolve_count": 0,
            "critic_feedback": None, "first_draft": None, "final_judgment": "",
            "user_preferences": combined_prefs, "numerical_validation": None,
            "raw_json": raw_json, "logs": []
        }
        return self.workflow.invoke(initial_state)

    def analyze_document(self, json_str: str, user_instruction: str = None):
        clean_json = json_str.strip()
        print(f"DEBUG [analyze_document]: clean_json (snippet): {clean_json[:100]}")
        llm = self.llm_manager.get_heavy_llm()
        # PREP 단계에서 새 쿼리 생성
        prep_res = llm.invoke(PREP_PROMPT.format(json_data=clean_json))
        def extract_tag(tag, text):
            match = re.search(f'<{tag}>(.*?)</{tag}>', text, re.DOTALL)
            return match.group(1).strip() if match else ""
        query = extract_tag("query", prep_res.content)
        jurisdiction = extract_tag("jurisdiction", prep_res.content)
        print(f"DEBUG [analyze_document]: Passing raw_json to run: {len(clean_json)} chars")
        return self.run(query, jurisdiction=jurisdiction, raw_json=clean_json, user_instruction=user_instruction)
