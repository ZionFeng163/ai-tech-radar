from app.editions import ManualRadarService


def test_quota_exhaustion_is_a_systemic_friendly_failure() -> None:
    error = (
        "Bailian returned HTTP 403 "
        "(AllocationQuota.FreeTierOnly: Free quota exhausted.)"
    )

    assert ManualRadarService._is_systemic_analysis_failure(error) is True
    assert ManualRadarService._friendly_analysis_error(error) == (
        "百炼免费额度已耗尽；请充值或在百炼控制台关闭“仅使用免费额度”后重试"
    )


def test_source_failures_are_summarized_without_leaking_long_responses() -> None:
    summary = ManualRadarService._source_failure_summary(
        [
            {
                "source": "arxiv",
                "status": "failed",
                "error": "Client error '429' for a very long URL",
            },
            {"source": "hacker-news", "status": "success"},
        ]
    )

    assert summary == "arxiv 请求频率受限"
