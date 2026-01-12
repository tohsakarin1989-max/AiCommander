from typing import Dict, Any, List
from sqlalchemy.orm import Session
from app.services.case_service import CaseService
from app.utils.geo import haversine_km


class GraphService:
    @staticmethod
    def build_serial_graph(
        db: Session,
        case_ids: List[int],
        radius_km: float = 2.0,
    ) -> Dict[str, Any]:
        cases = CaseService.get_cases_by_ids(db, case_ids)
        nodes = [
            {
                "id": c.id,
                "case_number": c.case_number,
                "case_type": c.case_type,
                "location": c.location,
                "latitude": c.latitude,
                "longitude": c.longitude,
                "modus_operandi": c.modus_operandi,
            }
            for c in cases
        ]

        edges = []
        for i in range(len(cases)):
            for j in range(i + 1, len(cases)):
                c1 = cases[i]
                c2 = cases[j]
                reasons = []
                score = 0.0

                if c1.case_type and c1.case_type == c2.case_type:
                    reasons.append("同类型")
                    score += 0.3
                if c1.modus_operandi and c1.modus_operandi == c2.modus_operandi:
                    reasons.append("同手法")
                    score += 0.4
                if c1.latitude and c1.longitude and c2.latitude and c2.longitude:
                    dist = haversine_km(c1.latitude, c1.longitude, c2.latitude, c2.longitude)
                    if dist <= radius_km:
                        reasons.append(f"距离{dist:.2f}km")
                        score += 0.3
                if reasons:
                    edges.append({
                        "source": c1.id,
                        "target": c2.id,
                        "reasons": reasons,
                        "score": round(score, 2),
                    })

        return {"nodes": nodes, "edges": edges}
