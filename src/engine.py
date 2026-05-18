"""
################################################################################
# 법률 검색 엔진 (src/engine.py)
# 
# [개발자 가이드]
# - ChromaDB와 SQLite를 사용하여 하이브리드 법률 조문 검색을 수행합니다.
# - BGE-M3 임베딩 모델을 사용하여 쿼리를 벡터화하고, SQL DB로 메타데이터와 조문 상세 정보를 결합합니다.
# - 하이브리드 검색: 벡터 유사도 기반 1단계 검색 → SQL 기반 상세 정보 조회 및 Mandatory/Graph 가중치 적용(2단계) → Law-Graph 이웃 조문 확장(3단계)
# 
# [주의사항]
# - 벡터 DB와 SQL DB 간의 article_id 매핑 무결성이 중요합니다.
# - 임베딩 모델 인스턴스는 메모리 효율을 위해 클래스 변수(_emb_fn)로 공유됩니다.
################################################################################
"""
import chromadb
...
import sqlite3
import os
from chromadb.utils import embedding_functions

# [v3.1] 개발 환경 경로 설정
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHROMA_DB_PATH = os.path.join(BASE_DIR, 'database', 'legal_chroma_db')
SQLITE_DB_PATH = os.path.join(BASE_DIR, 'database', 'legal_data.sqlite')
EMBEDDING_MODEL_NAME = "BAAI/bge-m3"

class LegalEngine:
    _emb_fn = None  # 임베딩 모델 공유를 위한 클래스 변수

    def __init__(self):
        if LegalEngine._emb_fn is None:
            print("🚀 Loading Embedding Model into Memory (once)...")
            LegalEngine._emb_fn = embedding_functions.SentenceTransformerEmbeddingFunction(model_name=EMBEDDING_MODEL_NAME)
        
        self.client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
        self.emb_fn = LegalEngine._emb_fn
        self.collection = self.client.get_collection(name="legal_provisions", embedding_function=self.emb_fn)
        self.conn = sqlite3.connect(SQLITE_DB_PATH, check_same_thread=False)
        self.cursor = self.conn.cursor()

    def hybrid_search(self, query, jurisdiction=None, category=None, n_results=10):
        import time
        start_total = time.time()
        
        # 가이드 2항: BGE-M3 Prefix 적용 및 법률 키워드 보강
        refined_query = query
        if any(k in query.lower() for k in ["liability", "risk", "mandatory", "exclude"]):
            refined_query += " mandatory provision liability exclusion"
            
        prefix_query = f"query: {refined_query}"
        
        # 필터링 조건 구성
        where_filter = {}
        if jurisdiction: 
            # [v3.3] 관할권 필터링 유연화: 콤마로 구분된 여러 국가 지원
            j_list = [j.strip() for j in jurisdiction.split(',')]
            if len(j_list) > 1:
                where_filter["jurisdiction"] = {"$in": j_list}
            else:
                where_filter["jurisdiction"] = j_list[0]
                
        if category: where_filter["category"] = category

        # 1단계: Vector 검색 (Recall)
        start_vector = time.time()
        results = self.collection.query(
            query_texts=[prefix_query],
            n_results=n_results * 2, # Re-ranking을 위해 2배수 추출
            where=where_filter if where_filter else None
        )
        
        # [v3.4] Fallback: 필터링 결과가 없으면 필터 없이 재검색
        if (not results['ids'] or not results['ids'][0]) and where_filter:
            print("⚠️ [Engine] No results with filter. Retrying without jurisdiction filter...")
            if "jurisdiction" in where_filter:
                temp_filter = where_filter.copy()
                del temp_filter["jurisdiction"]
                results = self.collection.query(
                    query_texts=[prefix_query],
                    n_results=n_results * 2,
                    where=temp_filter if temp_filter else None
                )
        
        vector_time = time.time() - start_vector

        final_docs = []
        if not results['ids'] or not results['ids'][0]: 
            print(f"⏱️ [Engine] Total: {time.time()-start_total:.2f}s (Vector: {vector_time:.2f}s, SQL: 0s) - No results")
            return final_docs

        # 2단계: SQL 상세 검증 및 Mandatory Boost 적용 + [v3.5] Law-Graph 관계 반영
        start_sql = time.time()
        for doc_id, dist, meta in zip(results['ids'][0], results['distances'][0], results['metadatas'][0]):
            article_id = meta.get("article_id")
            base_score = round((1 - dist) * 100, 2)
            
            # 기본 정보 조회
            self.cursor.execute("""
                SELECT a.content, a.article_no, l.law_name, l.jurisdiction, m.category, 
                       m.is_mandatory, m.analysis_reason, m.source_type
                FROM articles a
                JOIN laws l ON a.law_id = l.law_id
                JOIN article_metadata m ON a.article_id = m.article_id
                WHERE a.article_id = ?
            """, (article_id,))
            
            row = self.cursor.fetchone()
            if row:
                is_mandatory = row[5]
                # v3.2: 중요 조항 동적 가중치
                weight = 15.0 if is_mandatory else 0
                
                # [v3.5] Law-Graph 관계 가중치: 현재 조문과 연결된 다른 중요 조문이 있는지 체크
                self.cursor.execute("""
                    SELECT COUNT(*) FROM law_relationships 
                    WHERE source_id = ? OR target_id = ?
                """, (article_id, article_id))
                rel_count = self.cursor.fetchone()[0]
                graph_weight = min(rel_count * 5.0, 15.0) # 관계당 5점, 최대 15점 보너스
                
                final_score = base_score + weight + graph_weight
                
                final_docs.append({
                    "article_id": article_id,
                    "content": row[0],
                    "article_no": row[1],
                    "law_name": row[2],
                    "jurisdiction": row[3],
                    "category": row[4],
                    "is_mandatory": is_mandatory,
                    "reason": row[6],
                    "source_type": row[7],
                    "retrieval_score": min(final_score, 100.0)
                })
        sql_time = time.time() - start_sql
        
        # 3단계: Law-Graph 기반 지식 확장 (Graph Expansion)
        expanded_docs = final_docs.copy()
        top_ids = [d['article_id'] for d in final_docs[:3]] # 상위 3개 검색 결과의 이웃 탐색
        
        for art_id in top_ids:
            self.cursor.execute("""
                SELECT target_id FROM law_relationships WHERE source_id = ?
                UNION
                SELECT source_id FROM law_relationships WHERE target_id = ?
            """, (art_id, art_id))
            neighbors = self.cursor.fetchall()
            
            for (n_id,) in neighbors:
                # 이미 검색 결과에 있으면 패스
                if any(d['article_id'] == n_id for d in expanded_docs):
                    continue
                
                # 이웃 조문 상세 정보 조회
                self.cursor.execute("""
                    SELECT a.content, a.article_no, l.law_name, l.jurisdiction, m.category, 
                           m.is_mandatory, m.analysis_reason, m.source_type
                    FROM articles a
                    JOIN laws l ON a.law_id = l.law_id
                    JOIN article_metadata m ON a.article_id = m.article_id
                    WHERE a.article_id = ?
                """, (n_id,))
                row = self.cursor.fetchone()
                if row:
                    expanded_docs.append({
                        "article_id": n_id,
                        "content": row[0],
                        "article_no": row[1],
                        "law_name": row[2],
                        "jurisdiction": row[3],
                        "category": row[4],
                        "is_mandatory": row[5],
                        "reason": f"Graph Neighbor of {art_id}",
                        "source_type": row[7],
                        "retrieval_score": 75.0 # 그래프 이웃은 중간 정도의 고정 점수 부여 (통과 유도)
                    })
        
        print(f"⏱️ [Engine] Total: {time.time()-start_total:.2f}s | Original: {len(final_docs)} | Expanded: {len(expanded_docs)}")
        return expanded_docs[:n_results]
