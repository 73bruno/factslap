import httpx
import respx

from factslap.models import StudyType
from factslap.sources.europe_pmc import EuropePMC
from factslap.sources.fact_check import FactCheck
from factslap.sources.open_data import OpenFoodFacts
from factslap.sources.semantic_scholar import SemanticScholar
from factslap.sources.wikipedia import Wikipedia


@respx.mock
async def test_semantic_scholar_merges_abstracts_and_body_snippets():
    respx.get("https://api.semanticscholar.org/graph/v1/paper/search").respond(json={"data": [{
        "corpusId": 11, "title": "Knuckle cracking and arthritis", "abstract": "<p>No association was found.</p>",
        "year": 2011, "authors": [{"name": "Deweber K"}], "venue": "JABFM", "citationCount": 40,
        "externalIds": {"DOI": "10.3122/jabfm.2011.02.100156"}, "publicationTypes": ["JournalArticle"],
    }, {"corpusId": 12, "title": "No abstract paper", "abstract": None}]})
    respx.get("https://api.semanticscholar.org/graph/v1/snippet/search").respond(json={"data": [{
        "snippet": {"text": "Habitual crackers showed no higher prevalence of hand osteoarthritis.", "snippetKind": "body"},
        "score": 0.71, "paper": {"corpusId": "11", "title": "Knuckle cracking and arthritis", "authors": ["Deweber K"]},
    }]})
    async with httpx.AsyncClient() as client:
        s2 = SemanticScholar(api_key="k")
        s2.min_interval_s = 0
        passages = await s2.search(client, ["knuckle cracking arthritis"], "c", "en", 5)
    by_id = {p.id: p for p in passages}
    assert set(by_id) == {"s2:11:abstract", "s2:11:body:0"}
    assert by_id["s2:11:abstract"].text == "No association was found."
    assert by_id["s2:11:abstract"].doi.startswith("10.3122")
    assert by_id["s2:11:body:0"].corpus_id == 11 and by_id["s2:11:body:0"].source_score == 0.71
    assert respx.calls[0].request.headers["x-api-key"] == "k"


@respx.mock
async def test_europe_pmc_splits_abstracts_and_reads_study_types():
    long_abstract = " ".join(f"Sentence number {i} about caffeine and attention in adults." for i in range(60))
    respx.get("https://www.ebi.ac.uk/europepmc/webservices/rest/search").respond(json={"resultList": {"result": [{
        "id": "123", "source": "MED", "pmid": "123", "title": "Caffeine: a meta-analysis", "pubYear": "2024",
        "abstractText": f"<h4>Background</h4>{long_abstract}", "authorString": "Smith J, Doe A.",
        "pubTypeList": {"pubType": ["Meta-Analysis", "Journal Article"]}, "doi": "10.1/abc",
    }]}})
    async with httpx.AsyncClient() as client:
        passages = await EuropePMC().search(client, ["caffeine attention"], "c", "en", 5)
    assert len(passages) > 1  # long abstract split into overlapping windows
    assert all(p.study_type == StudyType.META_ANALYSIS for p in passages)
    assert passages[0].year == 2024 and passages[0].authors == ["Smith J", "Doe A."]
    assert "<h4>" not in passages[0].text


@respx.mock
async def test_wikipedia_uses_the_claim_language_first():
    route_es = respx.get("https://es.wikipedia.org/w/api.php").respond(json={"query": {"pages": {"1": {
        "pageid": 1, "index": 1, "title": "Artritis", "fullurl": "https://es.wikipedia.org/wiki/Artritis",
        "extract": "La artritis es la inflamación de una o varias articulaciones del cuerpo humano y sus causas.",
    }}}})
    respx.get("https://en.wikipedia.org/w/api.php").respond(json={"query": {"pages": {}}})
    async with httpx.AsyncClient() as client:
        passages = await Wikipedia().search(client, ["knuckle cracking"], "crujirse los dedos da artritis", "es", 4)
    assert route_es.called
    assert passages[0].lang == "es" and passages[0].study_type == StudyType.ENCYCLOPEDIA


@respx.mock
async def test_fact_check_sends_the_user_language_and_reads_every_review():
    route = respx.get("https://factchecktools.googleapis.com/v1alpha1/claims:search").respond(json={"claims": [{
        "text": "Cracking knuckles causes arthritis",
        "claimReview": [
            {"publisher": {"name": "Maldita"}, "url": "https://a", "textualRating": "Falso", "reviewDate": "2023-01-02"},
            {"publisher": {"name": "Newtral"}, "url": "https://b", "textualRating": "Bulo"},
        ],
    }]})
    async with httpx.AsyncClient() as client:
        passages = await FactCheck("key").search(client, [], "crujirse los dedos", "es", 5)
    assert route.calls[0].request.url.params["languageCode"] == "es"
    assert len(passages) == 2 and passages[0].year == 2023


async def test_fact_check_without_key_returns_nothing():
    assert await FactCheck(None).search(None, [], "x", "en", 5) == []


@respx.mock
async def test_open_food_facts_reports_data_not_opinions():
    respx.get("https://search.openfoodfacts.org/search").respond(json={"hits": [{
        "code": "1", "product_name": "Choco cereal", "brands": ["Acme"], "nutriments": {"sugars_100g": 31},
        "nutriscore_grade": "e", "nova_group": 4,
    }]})
    async with httpx.AsyncClient() as client:
        [p] = await OpenFoodFacts().search(client, [], "choco cereal is healthy", "en", 3)
    assert "sugars: 31 per 100 g" in p.text and "Nutri-Score: E" in p.text
    assert "(Acme)" in p.text
    assert "basura" not in p.text.lower()


@respx.mock
async def test_openalex_rebuilds_abstracts_and_skips_works_without_one():
    from factslap.sources.openalex import OpenAlex, rebuild_abstract

    assert rebuild_abstract({"sugar": [0], "does": [1], "not": [2], "matter": [3]}) == "sugar does not matter"
    words = " ".join(f"word{i}" for i in range(40))
    inverted = {w: [i] for i, w in enumerate(words.split())}
    respx.get("https://api.openalex.org/works").respond(json={"results": [
        {"id": "https://openalex.org/W1", "doi": "https://doi.org/10.1/x", "title": "Sugar and behavior: a meta-analysis",
         "publication_year": 1995, "cited_by_count": 300, "type": "article", "abstract_inverted_index": inverted},
        {"id": "https://openalex.org/W2", "title": "No abstract", "abstract_inverted_index": None},
    ]})
    async with httpx.AsyncClient() as client:
        passages = await OpenAlex().search(client, ["sugar behavior children"], "c", "en", 6)
    assert {p.id.split(":")[1] for p in passages} == {"W1"}
    assert passages[0].doi == "10.1/x" and passages[0].study_type == StudyType.META_ANALYSIS
