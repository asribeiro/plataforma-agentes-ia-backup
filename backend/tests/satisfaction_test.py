from backend.routes.satisfaction_routes import SatisfactionResponse


def test_satisfaction_scores_are_bounded():
    response = SatisfactionResponse(nps_score=9, procedure_score=5, comment="Muito bom")
    assert response.nps_score == 9
    assert response.procedure_score == 5
