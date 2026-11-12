"""A golden table of what `ats_detect.from_url`, `from_cname` and `from_html` return (issue #282).

Written against the if-chains the platform modules replaced and kept unchanged through the move:
the dispatcher must reproduce their precedence (the SmartRecruiters string form first, an HR-Manager
link before HR-ON, the order of the page-link platforms, the signature fallbacks last).
"""

import pytest

from door.core import ats_detect


def _d(det):
    return None if det is None else (det.platform, det.entry)


_URLS = [
    ('https://engradar.com/jobs/smartrecruiters:InterIKEAGroup:744000154654869', ('smartrecruiters', 'interikeagroup')),
    ('https://engradar.com/jobs/greenhouse:acme:1', None),
    ('https://boards.greenhouse.io/embed/job_board?for=acme', ('greenhouse', 'acme')),
    ('https://job-boards.greenhouse.io/trustpilot/jobs/7339851', ('greenhouse', 'trustpilot')),
    ('https://job-boards.eu.greenhouse.io/pandora', ('greenhouse', 'pandora')),
    ('https://boards.eu.greenhouse.io/', None),
    ('https://jobs.lever.co/kavak/abc-123', ('lever', 'kavak')),
    ('https://jobs.eu.lever.co/siteimprove', ('lever', 'siteimprove')),
    ('https://jobs.lever.co/', None),
    ('https://apply.workable.com/dreamdata/j/497E870DCF/', ('workable', 'dreamdata')),
    ('https://apply.workable.com/j/497E870DCF', None),
    ('https://jobs.ashbyhq.com/pleo/9c184331', ('ashby', 'pleo')),
    ('https://templafy.teamtailor.com/jobs/8483649-designer', ('teamtailor', 'templafy')),
    ('https://www.teamtailor.com/en/', None),
    ('https://cdn.jobylon.com/jobs/companies/2420/embed/v2/', ('jobylon', '2420')),
    ('https://emp.jobylon.com/jobs/393911-lyko-butikschef-till-lyko-marieberg/', ('jobylon', None)),
    ('https://emp.jobylon.com/applications/jobs/393911/create/', ('jobylon', None)),
    ('https://emp.jobylon.com/accounts/login/', None),
    ('https://famly.recruitee.com/o/senior-engineer', ('recruitee', 'famly')),
    ('https://careers.recruitee.com/o/x', None),
    ('https://factbird.pinpointhq.com/en/postings/996b5103', ('pinpoint', 'factbird')),
    ('https://a.b.pinpointhq.com/x', None),
    ('https://api.hr-manager.net/JobPortal.svc/kkdk/PositionList/json/', ('hr_manager', 'kkdk')),
    ('https://candidate.hr-manager.net/Agent/Subscription.aspx?customer=regionh', ('hr_manager', 'regionh')),
    ('https://candidate.hr-manager.net/ApplicationInit.aspx?cid=342&ProjectId=1', ('hr_manager', None)),
    ('https://candidate.hr-manager.net/Vacancies/List.aspx', None),
    ('https://candidate.hr-manager.net/ApplicationInit.aspx?cid=342&hr=show-job/1', ('hr_manager', None)),
    ('https://www.dalux.com/careers/job?hr=show-job/327277&locale=en_US', ('hr_on', None)),
    ('https://bankinvest.hr-on.com/show-job/357305?linkref=1', ('hr_on', None)),
    ('https://greenhouse.io/x?hr=show-job/1', ('hr_on', None)),
    ('https://recruit.visma.com/spa/public/apply?guidAssignment=2b368797-8e2c-4527-bc80-7cc9ac2d9c39', ('visma_recruit', None)),
    ('https://www.visma.se/karriar', None),
    ('https://novonordisk.jobs2web.com/job/x/123/', ('successfactors', 'novonordisk.jobs2web.com')),
    ('https://velux.wd3.myworkdayjobs.com/en-US/Velux_Commercial/job/x', ('career_sites', 'https://velux.wd3.myworkdayjobs.com')),
    ('https://wd3.myworkdaysite.com/recruiting/velux/Velux_Commercial/job/x', ('career_sites', 'https://velux.wd3.myworkdayjobs.com')),
    ('https://wd3.myworkdaysite.com/other/velux/x', None),
    ('https://efzu.fa.em2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/job/8384', ('oracle_hcm', 'efzu.fa.em2.oraclecloud.com/CX_1')),
    ('https://efzu.fa.em2.oraclecloud.eu/hcmUI/CandidateExperience/en/sites/CX_1/job/8384', ('oracle_hcm', 'efzu.fa.em2.oraclecloud.eu/CX_1')),
    ('https://efzu.fa.em2.oraclecloud.com/other/path', None),
    ('https://jobs.dayforcehcm.com/en-US/natus/CANDIDATEPORTALSENSORY/jobs/3288', ('dayforce', 'natus/CANDIDATEPORTALSENSORY')),
    ('https://jobs.dayforcehcm.com/natus/CANDIDATEPORTALSENSORY/jobs/3288', ('dayforce', 'natus/CANDIDATEPORTALSENSORY')),
    ('https://jobs.dayforcehcm.com/en-US/natus/CANDIDATEPORTALSENSORY', ('dayforce', 'natus/CANDIDATEPORTALSENSORY')),
    ('https://jobs.dayforcehcm.com/zh-Hans-SG/Acme/External', ('dayforce', 'acme/External')),
    ('https://jobs.dayforcehcm.com/en-US', None),
    ('https://portal.signatur.dk/ExtJobs/DefaultHosting/JobApplication.aspx?ClientId=1449&ERId=131713', ('signatur', '1449')),
    ('https://portal.signatur.dk/ExtJobs/DefaultHosting/JobList.aspx?clientid=2296', ('signatur', '2296')),
    ('https://portal.signatur.dk/ExtJobs/DefaultHosting/Default.aspx', None),
    ('https://pnty-apply.ponty-system.se/aldeaexecutivesearch?id=74', ('ponty', None)),
    ('https://www.ponty.se/', None),
    ('https://jobaffinity.fr/apply/wqrlmvgzpyc67d0izf', ('jobaffinity', None)),
    ('https://notjobaffinity.fr/apply/x', None),
    ('https://web103.reachmee.com/ext/I003/354/main?site=5&validator=abc&lang=SE&rmpage=job&rmjob=12986', ('reachmee', 'I003/354/5')),
    ('https://web103.reachmee.com/ext/I003/354/job?site=12&lang=UK&validator=abc&job_id=12985', ('reachmee', 'I003/354/12')),
    ('https://web103.reachmee.com/customerjs/I021-1746-6.js', ('reachmee', 'I021/1746/6')),
    ('https://site106.reachmee.com/Public/rssfeed/external.ashx?id=5&InstallationID=I003&CustomerName=oru', ('reachmee', None)),
    ('https://www.reachmee.com/', None),
    ('https://ki.varbi.com/en/what:job/jobID:985204/', ('varbi', 'ki')),
    ('https://uu.varbi.com/se/what:job/jobID:1/type:job/apply:1/', ('varbi', 'uu')),
    ('https://www.varbi.com/se/', None),
    ('https://pno-group-europe.jobs.personio.com/job/2803716', ('personio', 'pno-group-europe')),
    ('https://acme.jobs.personio.de/job/55?language=de', ('personio', 'acme.jobs.personio.de')),
    ('https://www.personio.com/', None),
    ('https://agrica-career.talent-soft.com/offre-de-emploi/emploi-analyste-data-h-f_2286.aspx', ('talentsoft', 'agrica-career.talent-soft.com')),
    ('https://recrutement.example.fr/handlers/offerRss.ashx?LCID=1036', ('talentsoft', 'recrutement.example.fr')),
    ('https://www.talent-soft.com/fr/', None),
    ('https://acme.digitalrecruiters.com/fr/annonces', ('digitalrecruiters', 'acme.digitalrecruiters.com')),
    ('https://app.digitalrecruiters.com/connexion', None),
    ('https://profile.varbi.com/login/', None),
    ('https://vitalityweb.eploy.net/vacancies/21883/head-of-events-and-experiences.html', ('eploy', 'vitalityweb.eploy.net')),
    ('https://www.eploy.net/', None),
    ('https://careers-sisk.icims.com/jobs/3203/site-manager--/job?in_iframe=1', ('icims', None)),
    ('https://www.icims.com/', None),
    ('https://pn.recman.page/job/429148', ('recman', 'pn')),
    ('https://yourstaff.recman.io/jobs', ('recman', 'yourstaff.recman.io')),
    ('https://apply.recman.page/job_post.php?id=429148&sub_id=985&path=ams', ('recman', None)),
    ('https://www.recman.io/', None),
    ('https://donecle.taleez.com/en', ('taleez', 'donecle')),
    ('https://taleez.com/apply/sp/donecle', ('taleez', 'donecle')),
    ('https://taleez.com/apply/responsable-rh-toulouse-donecle-cdi', None),
    ('https://careers.flatchr.io/fr/company/acme/vacancy/abc-dev', ('flatchr', 'acme')),
    ('https://acme.flatchr.io/', ('flatchr', 'acme')),
    ('https://www.flatchr.io/cgu', None),
    ('https://www.jobtrain.co.uk/leighacademiestrust/Job/JobDetail?JobId=8691', ('jobtrain', 'leighacademiestrust')),
    ('https://www.jobtrain.co.uk/', None),
    ('https://www.networxrecruitment.com/Jobs/Advert/3382599?cid=1491&js=0', ('networx', '1491')),
    ('https://current-vacancies.com/jobs/advert/4210730?cid=1616', ('networx', '1616')),
    ('https://www.networxrecruitment.com/Website/Search?SelectedEmployers=3509', ('networx', '3509')),
    ('https://www.networxrecruitment.com/', None),
    ('https://giboire.nous-recrutons.fr/poste/0iwubmg1rl-responsable-developpement/', ('beetween', 'giboire')),
    ('https://www.nous-recrutons.fr/', None),
    ('https://jobs.smartrecruiters.com/NCS3/6000000001373525-it-support', ('smartrecruiters', 'ncs3')),
    ('https://careers.smartrecruiters.com/InterIKEAGroup', ('smartrecruiters', 'interikeagroup')),
    ('https://jobs.smartrecruiters.com/', None),
    ('https://au.smrtr.io/k7kb', ('smartrecruiters', None)),
    ('https://career2.successfactors.eu/career?company=x', None),
    ('https://www.jobindex.dk/jobannonce/h1673146/', None),
    ('https://acme.dk/careers', None),
    ('not a url', None),
]

_CNAMES = [
    ('ext.teamtailor.com.', ('teamtailor', 'careers.veo.co')),
    ('novonordisk.jobs2web.com', ('successfactors', 'careers.veo.co')),
    ('secure.recruitee.com', ('recruitee', 'careers.veo.co')),
    ('veo.talentbrew.com', ('career_sites', 'https://careers.veo.co')),
    ('veo.icims.com', ('career_sites', 'https://careers.veo.co')),
    ('lego.phenompeople.net', ('phenom', None)),
    ('signo.recman.page.', ('recman', 'signo')),
    ('acme-career.talent-soft.com.', ('talentsoft', 'acme-career.talent-soft.com')),
    ('apply.recman.page', None),
    ('donecle.taleez.com', ('taleez', 'donecle')),
    ('www.taleez.com', None),
    ('jobs-crisis.jobtrain.co.uk', ('jobtrain', 'careers.veo.co')),
    ('www.jobtrain.co.uk', None),
    ('giboire.nous-recrutons.fr.', ('beetween', 'giboire')),
    ('velux.wd3.myworkdayjobs.com', ('career_sites', 'https://velux.wd3.myworkdayjobs.com')),
    ('a.b.wd3.myworkdayjobs.com', None),
    ('acme.github.io', None),
    ('', None),
]

_HTMLS = {
    'gh': '<script src="https://boards.greenhouse.io/embed/job_board/js?for=trustpilot"></script>',
    'home': '<a href="https://www.teamtailor.com/">x</a> <a href="https://recruitee.com/">x</a>',
    'pin': '<a href="https://factbird.pinpointhq.com/en/postings/x">Apply</a>',
    'sr': '<a href="https://jobs.smartrecruiters.com/NCS3/6000000001373525-x">Apply</a>',
    'multi': '<a href="https://jobs.lever.co/a/1">x</a><a href="https://boards.greenhouse.io/b">y</a>',
    'multi2': '<a href="https://velux.wd3.myworkdayjobs.com/x/job/1">x</a><a href="https://novonordisk.jobs2web.com/job/x">y</a>',
    'multi3': '<a href="https://jobs.smartrecruiters.com/NCS3/1">x</a><a href="https://efzu.fa.em2.oraclecloud.com/hcmUI/x/1">y</a><a href="https://jobs.dayforcehcm.com/n/P">z</a>',
    'hron': '<a href="https://bankinvest.hr-on.com/show-job/1">x</a>',
    'vismaad': '<a href="https://recruit.visma.com/spa/public/apply?guidAssignment=2b368797-8e2c-4527-bc80-7cc9ac2d9c39">Ansök</a>',
    'hrframe': '<script src="https://recruit.hr-on.com/frame-api/customers/dalux.js?"></script>',
    'rec': '{"assetHost":"https://x.recruiteecdn.com"} trackman.recruitee.com',
    'jbl': '<script>jbl_company_id = 2631; jbl_version = "v2";</script><script src="https://cdn.jobylon.com/embedder.js"></script>',
    'jbliframe': '<iframe src="https://cdn.jobylon.com/jobs/companies/2420/embed/v2/?target=x"></iframe>',
    'tt': '<link href="https://assets.teamtailor-cdn.com/assets/careersite.css">',
    'rmk': '<script src="https://rmkcdn.successfactors.com/abc/js/x.js"></script>',
    'j2w': '<a>jobs2web</a>',
    'ld': '<script type="application/ld+json">{"@type": "JobPosting", "title": "A"}</script>',
    'ld2': '{"@type": ["Thing","JobPosting"]}',
    'recman': '<script src="https://cp-analytics.recman.io"></script> {"@type": "JobPosting"}',
    'flatchr': '<a href="https://careers.flatchr.io/fr/company/acme/vacancy/x">Postuler</a>',
    'jobtrain': "<script>var SITE_BASE_PATH='/leighacademiestrust/'\nvar Site_Client_Name='leighacademiestrust'</script>",
    'jobtrainhost': "<script>var SITE_BASE_PATH='/'\nvar Site_Client_Name='crisis'</script>"
                    '<script type="application/ld+json">{"@type": "JobPosting", "title": "A"}</script>',
    'beetween': '<link href="/wp-content/themes/x/style.css"><a href="https://careers.trackman.com/poste/tcd9cr0cgv-chef-de-projet/">Voir</a>',
    'dr': '<script>window.__NUXT__={config:{public:{apiBaseURL:"https:\\u002F\\u002Fapi.digitalrecruiters.com\\u002Fcareers\\u002Fv1"}},pinia:{careersSite:{careersSite:{domain_name:"recrutement.acme.fr"}}}}</script>',
    'drad': '<script>{apiBaseURL:"https://api.digitalrecruiters.com/careers/v1"}</script><script type="application/ld+json">{"@type": "JobPosting", "title": "A"}</script>',
    'eploy': '<a href="/vacancies/vacancy-search-results.aspx">Jobs</a><p>Powered by <a rel=\'nofollow\' href=\'https://www.eploy.co.uk\'>Eploy</a></p><script type="application/ld+json">{"@type": "JobPosting", "title": "A"}</script>',
    'none': '<p>nothing</p>',
    'recld': '<x recruiteecdn.com/> {"@type": "JobPosting"}',
    'nolinkentry': '<a href="https://candidate.hr-manager.net/ApplicationInit.aspx?cid=3">x</a><a href="https://api.hr-manager.net/JobPortal.svc/kk/PositionList/json/">y</a>',
}

_HTML_EXPECTED = {
    'gh': ('greenhouse', 'trustpilot'),
    'home': None,
    'pin': ('pinpoint', 'factbird'),
    'sr': ('smartrecruiters', 'ncs3'),
    'multi': ('greenhouse', 'b'),
    'multi2': ('successfactors', 'novonordisk.jobs2web.com'),
    'multi3': ('oracle_hcm', None),
    'hron': None,
    'hrframe': ('hr_on', None),
    'vismaad': ('visma_recruit', None),
    'rec': ('recruitee', 'careers.trackman.com'),
    'jbl': ('jobylon', '2631'),
    'jbliframe': ('jobylon', '2420'),
    'tt': ('teamtailor', 'careers.trackman.com'),
    'rmk': ('successfactors', 'careers.trackman.com'),
    'j2w': ('successfactors', 'careers.trackman.com'),
    'ld': ('career_sites', 'https://careers.trackman.com'),
    'ld2': ('career_sites', 'https://careers.trackman.com'),
    'recman': ('recman', 'careers.trackman.com'),
    'flatchr': ('flatchr', 'acme'),
    'jobtrain': ('jobtrain', 'leighacademiestrust'),
    'jobtrainhost': ('jobtrain', 'careers.trackman.com'),
    'beetween': ('beetween', 'careers.trackman.com'),
    'dr': ('digitalrecruiters', 'recrutement.acme.fr'),
    'drad': ('digitalrecruiters', 'careers.trackman.com'),
    'eploy': ('eploy', 'careers.trackman.com'),
    'none': None,
    'recld': ('recruitee', 'careers.trackman.com'),
    'nolinkentry': ('hr_manager', 'kk'),
}


@pytest.mark.parametrize("url, expected", _URLS)
def test_from_url_golden(url, expected):
    assert _d(ats_detect.from_url(url)) == expected


@pytest.mark.parametrize("cname, expected", _CNAMES)
def test_from_cname_golden(cname, expected):
    assert _d(ats_detect.from_cname("careers.veo.co", cname)) == expected


@pytest.mark.parametrize("name", list(_HTMLS))
def test_from_html_golden(name):
    assert _d(ats_detect.from_html(_HTMLS[name], "https://careers.trackman.com/x")) == _HTML_EXPECTED[name]
