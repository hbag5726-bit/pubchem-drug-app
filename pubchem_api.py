"""PubChem 공식 API(PUG REST, PUG View) 호출 모듈.

- 웹 페이지 스크래핑 없이 공식 API만 사용한다.
- 모든 요청은 레이트 리미터를 거쳐 초당 5회를 넘지 않는다.
"""
import threading
import time

import requests

PUG_REST = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
PUG_VIEW = "https://pubchem.ncbi.nlm.nih.gov/rest/pug_view"
COMPOUND_PAGE = "https://pubchem.ncbi.nlm.nih.gov/compound/"

TIMEOUT = 10  # 초
MIN_INTERVAL = 0.25  # 요청 간 최소 간격(초) -> 초당 최대 4회

# 실제 응답으로 확인한 물성 속성 이름
PROPERTIES = "MolecularFormula,MolecularWeight,IUPACName,SMILES,XLogP"


class PubChemError(Exception):
    """화면에 그대로 보여줄 수 있는 안내 문구를 담은 예외."""


class NotFoundError(PubChemError):
    """404: 해당 화합물/정보 없음."""


# ---------------------------------------------------------------- 레이트 리미터
_lock = threading.Lock()
_last_call = 0.0
_session = requests.Session()
_session.headers.update({"User-Agent": "pubchem-drug-app/1.0 (educational)"})


def _get(url):
    """레이트 리미트를 지키며 GET 요청. 오류는 PubChemError로 변환한다."""
    global _last_call
    with _lock:  # 여러 사용자 세션이 동시에 와도 간격 유지
        wait = MIN_INTERVAL - (time.monotonic() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()
    try:
        resp = _session.get(url, timeout=TIMEOUT)
    except requests.Timeout:
        raise PubChemError("PubChem 서버 응답이 늦어 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요.")
    except requests.RequestException:
        raise PubChemError("네트워크 오류로 PubChem에 연결하지 못했습니다. 인터넷 연결을 확인해 주세요.")
    if resp.status_code == 404:
        raise NotFoundError("검색 결과가 없습니다. 영어 이름의 철자를 확인해 주세요.")
    if resp.status_code in (429, 503):
        raise PubChemError("PubChem 서버가 혼잡합니다. 잠시 후 다시 시도해 주세요.")
    if not resp.ok:
        raise PubChemError(f"PubChem 서버 오류가 발생했습니다. (HTTP {resp.status_code})")
    return resp


# ---------------------------------------------------------------- PUG REST
def get_cid(name):
    """영어 이름 -> CID (가장 첫 번째 결과)."""
    from urllib.parse import quote
    data = _get(f"{PUG_REST}/compound/name/{quote(name.strip())}/cids/JSON").json()
    return data["IdentifierList"]["CID"][0]


def get_properties(cid):
    """CID -> 물성 dict (MolecularFormula, MolecularWeight, IUPACName, SMILES, XLogP)."""
    data = _get(f"{PUG_REST}/compound/cid/{cid}/property/{PROPERTIES}/JSON").json()
    return data["PropertyTable"]["Properties"][0]


def get_structure_png(cid):
    """CID -> 구조 이미지 PNG 바이트."""
    return _get(f"{PUG_REST}/compound/cid/{cid}/PNG").content


# ---------------------------------------------------------------- PUG View
def _find_section(sections, heading):
    """중첩된 Section 트리에서 TOCHeading이 일치하는 섹션을 재귀 탐색."""
    for sec in sections:
        if sec.get("TOCHeading") == heading:
            return sec
        found = _find_section(sec.get("Section", []), heading)
        if found:
            return found
    return None


def parse_ghs(record):
    """PUG View 응답(Record)에서 GHS 정보를 추출한다.

    출처(ReferenceNumber)별로 같은 항목이 반복되므로,
    Signal 또는 Hazard Statements가 있는 첫 번째 출처의 묶음을 사용한다.
    GHS 정보가 없으면 None.
    """
    sec = _find_section(record.get("Section", []), "GHS Classification")
    if not sec:
        return None

    # 출처 번호별로 항목 묶기 (등장 순서 유지)
    groups = {}
    for info in sec.get("Information", []):
        groups.setdefault(info.get("ReferenceNumber"), {})[info.get("Name")] = info

    sources = {r["ReferenceNumber"]: r.get("SourceName", "") for r in record.get("Reference", [])}

    def strings(info):
        items = info.get("Value", {}).get("StringWithMarkup", []) if info else []
        return items

    for ref, items in groups.items():
        signal = [s["String"] for s in strings(items.get("Signal"))]
        statements = [s["String"] for s in strings(items.get("GHS Hazard Statements"))]
        pictograms = []
        for s in strings(items.get("Pictogram(s)")):
            for m in s.get("Markup", []):
                if m.get("Type") == "Icon" and m.get("URL"):
                    pictograms.append({"url": m["URL"], "label": m.get("Extra", "")})
        if not (signal or statements or pictograms):
            continue
        return {
            "signal": signal[0] if signal else None,
            "statements": statements,
            "pictograms": pictograms,
            "source": sources.get(ref, ""),
        }
    return None


def get_ghs(cid):
    """CID -> GHS 정보 dict, 없으면 None (PUG View)."""
    try:
        data = _get(f"{PUG_VIEW}/data/compound/{cid}/JSON?heading=GHS+Classification").json()
    except NotFoundError:
        return None  # GHS 정보가 등록되지 않은 화합물
    return parse_ghs(data.get("Record", {}))


def pubchem_url(cid):
    """PubChem 화합물 페이지 링크(출처 표기용)."""
    return f"{COMPOUND_PAGE}{cid}"
