import os
import sys
import argparse
import json
from pathlib import Path

# 將當前目錄加入 python path，確保能 import agentic_memory
A_MEM_ROOT = Path(__file__).resolve().parent
if str(A_MEM_ROOT) not in sys.path:
    sys.path.insert(0, str(A_MEM_ROOT))

# 將 Repo 根目錄加入 python path，方便讀取其他模組
REPO_ROOT = A_MEM_ROOT.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agentic_memory.memory_system import AgenticMemorySystem

def load_l1_from_tree(tree_path: Path) -> list[dict]:
    """
    從 share_mem/tree.json 中讀取已切分好的結構化 L1 記憶物件
    """
    if not tree_path.exists():
        print(f"❌ tree.json file not found at: {tree_path}")
        sys.exit(1)
        
    print(f"📖 Reading structured L1 memory objects from {tree_path}...")
    with open(tree_path, 'r', encoding='utf-8') as f:
        tree = json.load(f)
    
    notes = []
    for meeting in tree.get("meetings", []):
        meeting_id = meeting.get("meeting_id")
        meeting_date = meeting.get("meeting_date")
        for obj in meeting.get("memory_objects", []):
            # 格式化為 A-mem 可以接收的 metadata 格式
            notes.append({
                "id": obj.get("obj_id"),
                "content": obj.get("content"),
                "tags": obj.get("related_topics", []),
                "category": obj.get("type", "General"),
                # A-mem timestamp 格式通常為 YYYYMMDDHHmm
                "timestamp": meeting_date.replace("-", "") + "0000" if meeting_date else "202601010000"
            })
    return notes

def load_raw_transcripts(transcript_dir: Path, chunk_size: int = 15) -> list[dict]:
    """
    直接從原始的 txt 逐字稿資料夾讀入對話，並切分成 coherent chunks
    """
    if not transcript_dir.exists():
        print(f"❌ Transcript directory not found at: {transcript_dir}")
        sys.exit(1)
        
    print(f"📖 Reading raw transcripts from {transcript_dir}...")
    notes = []
    # 遍歷目錄下的 txt 檔案
    for file_path in transcript_dir.glob("*.txt"):
        meeting_name = file_path.stem  # 例如 0307 或 Bdb001
        with open(file_path, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]
        
        # 每 chunk_size 行為一個 chunk
        for i in range(0, len(lines), chunk_size):
            chunk_lines = lines[i:i+chunk_size]
            content = "\n".join(chunk_lines)
            chunk_id = f"{meeting_name}-chunk-{i//chunk_size:03d}"
            notes.append({
                "id": chunk_id,
                "content": content,
                "tags": [meeting_name, "raw_transcript"],
                "category": "TranscriptChunk",
                "timestamp": "202601010000"  # 預設時間戳
            })
    return notes

def build_amem_system(notes: list[dict], use_llm_evolution: bool = False) -> AgenticMemorySystem:
    """
    實例化 A-mem 系統並將 notes 加載到 ChromaDB 之中
    """
    # 如果不啟用 LLM evolution，我們 Monkey patch 來避免耗時又昂貴的 LLM 呼叫
    if not use_llm_evolution:
        print("⚡ Monkey-patching AgenticMemorySystem to skip LLM evolution for fast loading...")
        # 覆蓋 process_memory 方法，直接返回 False (表示不進行演化) 與原來的 note
        AgenticMemorySystem.process_memory = lambda self, note: (False, note)
        # 覆蓋 analyze_content 方法，返回空 metadata
        AgenticMemorySystem.analyze_content = lambda self, content: {"keywords": [], "context": "General", "tags": []}

    print(f"📥 Loading {len(notes)} notes into Agentic Memory System (ChromaDB in-memory)...")
    
    # 初始化 A-mem
    # 因為我們不進行 LLM 呼叫，所以 backend 可以隨便填 (或如果需要 LLM，請填入合適的 API KEY)
    memory_system = AgenticMemorySystem(
        model_name='all-MiniLM-L6-v2',
        llm_backend="openai",
        llm_model="gpt-4o-mini"
    )
    
    for idx, note in enumerate(notes):
        memory_system.add_note(
            content=note["content"],
            id=note["id"],
            tags=note["tags"],
            category=note["category"],
            timestamp=note["timestamp"]
        )
        if (idx + 1) % 50 == 0:
            print(f"   Processed {idx + 1}/{len(notes)} notes...")
            
    print("✅ All notes loaded into A-mem ChromaDB.")
    return memory_system

def run_retrieval_evaluation(memory_system: AgenticMemorySystem, queries_path: Path, k: int = 5):
    """
    載入評估 queries 檔，對 A-mem 發送檢索並計算 Recall 與 Hit Rate
    """
    if not queries_path.exists():
        print(f"⚠️ Queries file not found at {queries_path}. Skipping evaluation runner.")
        return
        
    print(f"📖 Loading queries from {queries_path}...")
    queries = []
    with open(queries_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                queries.append(json.loads(line))
                
    print(f"🔎 Running evaluation on {len(queries)} queries...")
    results_report = []
    total_strict_recall = 0.0
    total_expected_recall = 0.0
    
    for q in queries:
        query_text = q["query"]
        strict_gold = set(q.get("strict_gold_obj_ids", []))
        expected_gold = set(q.get("expected_obj_ids", []))
        
        # 呼叫 A-mem search 
        retrieved = memory_system.search_agentic(query_text, k=k)
        retrieved_ids = [res["id"] for res in retrieved]
        retrieved_set = set(retrieved_ids)
        
        # 計算 recall
        strict_hit = strict_gold & retrieved_set
        strict_recall = len(strict_hit) / len(strict_gold) if strict_gold else 1.0
        
        expected_hit = expected_gold & retrieved_set
        expected_recall = len(expected_hit) / len(expected_gold) if expected_gold else 1.0
        
        total_strict_recall += strict_recall
        total_expected_recall += expected_recall
        
        results_report.append({
            "query": query_text,
            "strict_gold_ids": list(strict_gold),
            "expected_gold_ids": list(expected_gold),
            "retrieved_ids": retrieved_ids,
            "strict_recall": round(strict_recall, 4),
            "expected_recall": round(expected_recall, 4)
        })
        
    avg_strict_recall = total_strict_recall / len(queries) if queries else 0.0
    avg_expected_recall = total_expected_recall / len(queries) if queries else 0.0
    
    print("\n" + "="*50)
    print("📊 Evaluation Summary (A-mem Retrieval vs Gold L1):")
    print(f"   Total Queries: {len(queries)}")
    print(f"   Top-K Retrieved: {k}")
    print(f"   Average Strict Gold Recall: {avg_strict_recall:.4f}")
    print(f"   Average Expected Gold Recall: {avg_expected_recall:.4f}")
    print("="*50 + "\n")
    
    return {
        "avg_strict_recall": avg_strict_recall,
        "avg_expected_recall": avg_expected_recall,
        "detailed_results": results_report
    }

def main():
    parser = argparse.ArgumentParser(description="Load transcripts and evaluate A-mem retrieval.")
    parser.add_argument("--mode", choices=["l1-tree", "raw-grace", "raw-icsi"], default="l1-tree",
                        help="Data loading mode: 'l1-tree' (from share_mem/tree.json), 'raw-grace' (raw grace txt files), 'raw-icsi' (raw ICSI txt files)")
    parser.add_argument("--k", type=int, default=5, help="Number of retrieved results for evaluation")
    parser.add_argument("--chunk-size", type=int, default=15, help="Dialogue line count per chunk for raw mode")
    parser.add_argument("--use-llm", action="store_true", help="Enable LLM evolution during load (Warning: will make many LLM calls!)")
    args = parser.parse_args()
    
    notes = []
    
    if args.mode == "l1-tree":
        tree_path = REPO_ROOT / "share_mem" / "tree.json"
        notes = load_l1_from_tree(tree_path)
    elif args.mode == "raw-grace":
        transcript_dir = REPO_ROOT / "meeting_recording" / "transcript" / "grace"
        notes = load_raw_transcripts(transcript_dir, chunk_size=args.chunk_size)
    elif args.mode == "raw-icsi":
        transcript_dir = REPO_ROOT / "meeting_recording" / "transcript" / "ISCI"
        notes = load_raw_transcripts(transcript_dir, chunk_size=args.chunk_size)
        
    print(f"🎉 Prepared {len(notes)} notes using mode: {args.mode}")
    
    # 建立與載入
    memory_system = build_amem_system(notes, use_llm_evolution=args.use_llm)
    
    # 如果是 l1-tree，因為帶有 L1 obj_ids，可以跑我們的 gold queries 評估
    if args.mode == "l1-tree":
        queries_path = REPO_ROOT / "long_term" / "eval" / "long_term_retrieval_queries.jsonl"
        run_retrieval_evaluation(memory_system, queries_path, k=args.k)
    else:
        print("💡 Note: Raw transcripts loaded. Real-time recall is available. Try entering a query to search.")
        # 示範一次檢索
        query = "memory lifecycle"
        print(f"\n🔍 Searching for: '{query}'")
        results = memory_system.search_agentic(query, k=args.k)
        for res in results:
            print(f" - [{res['id']}] {res['content'][:150]}...")

if __name__ == "__main__":
    main()
