

def test_non_local_counts_accumulate_per_source_until_drained():
    from door.scrapers import drain_non_local, record_non_local

    drain_non_local("career_sites")
    record_non_local("career_sites", 3)
    record_non_local("career_sites", 4)
    record_non_local("smartrecruiters", 0)
    assert drain_non_local("career_sites") == 7 and drain_non_local("career_sites") == 0
    assert drain_non_local("smartrecruiters") == 0
