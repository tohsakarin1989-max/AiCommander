"""精确名次融合；只保留两支前 100 项正文，完整名次由轻量分数记录计算。"""
import heapq

FUSION_VERSION = 'history-rrf-60-5.1-1'
MIN_SEMANTIC_SUPPORT = 0.5  # 检索阈值，不是概率；业务效果需另行评测。


class HistoryRankFusion:
    def __init__(self):
        self.scores = []
        self.lexical = []
        self.semantic = []

    def add(self, item, similarity):
        lexical = item['score']
        # 已知表述完全相反时，不能靠向量词面接近重新补成肯定匹配。
        if item['different_conditions'] and not item['shared_conditions']:
            similarity = None
        semantic = similarity if similarity is not None and similarity >= MIN_SEMANTIC_SUPPORT else None
        if lexical <= 0 and semantic is None:
            return
        serial = len(self.scores)
        self.scores.append((serial, lexical if lexical > 0 else None, semantic))
        for heap, score in ((self.lexical, lexical if lexical > 0 else None), (self.semantic, semantic)):
            if score is None:
                continue
            entry = (score, -serial, item)
            if len(heap) < 100:
                heapq.heappush(heap, entry)
            elif entry[:2] > heap[0][:2]:
                heapq.heapreplace(heap, entry)

    def finish(self, limit):
        ranks = []
        for position in (1, 2):
            ordered = sorted((row for row in self.scores if row[position] is not None),
                             key=lambda row: (-row[position], row[0]))
            ranks.append({row[0]: rank for rank, row in enumerate(ordered, 1)})
        candidates = {-serial: item for _, serial, item in self.lexical + self.semantic}
        ranked = []
        for serial, item in candidates.items():
            score = sum(1 / (60 + rank[serial]) for rank in ranks if serial in rank)
            ranked.append((score, -serial, {**item, 'score': round(score, 8),
                'lexical_rank': ranks[0].get(serial), 'semantic_rank': ranks[1].get(serial),
                'matching_basis': '结构词项与本地语义联合检索，名次不是准确概率',
                'versions': {**item['versions'], 'fusion_version': FUSION_VERSION}}))
        # For limit <= 20, an item outside both top-100 has at most 2/161 support,
        # below at least limit entries in either branch (>= 1/(60+limit)).
        return [item for _, _, item in sorted(ranked, key=lambda row: row[:2], reverse=True)[:limit]]
