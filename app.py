"""생활 속 약물 정보 조회 앱 (PubChem 공식 API 기반) - 화면 담당."""
import re

import streamlit as st

import pubchem_api as api

# 대표 약물 목록: 한글 표시명 -> 영어 이름 (한글로 검색하면 404이므로 매핑 사용)
DRUGS = {
    "아세트아미노펜": "Acetaminophen",
    "이부프로펜": "Ibuprofen",
    "아스피린": "Aspirin",
    "카페인": "Caffeine",
    "비타민 C": "Ascorbic acid",
}
CUSTOM = "직접 입력 (영어 이름)"
CACHE_TTL = 24 * 3600  # 같은 약물은 24시간 동안 재호출하지 않음


# ---------------------------------------------------------------- 캐시 래퍼
# 예외가 발생하면 st.cache_data는 결과를 저장하지 않으므로 실패는 캐시되지 않는다.
@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def cached_cid(name):
    return api.get_cid(name)


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def cached_props(cid):
    return api.get_properties(cid)


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def cached_png(cid):
    return api.get_structure_png(cid)


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def cached_ghs(cid):
    return api.get_ghs(cid)


# ---------------------------------------------------------------- 화면
st.set_page_config(page_title="생활 속 약물 정보", page_icon="💊")
st.title("💊 생활 속 약물 정보 조회")
st.caption("PubChem 공식 API(PUG REST / PUG View)로 조회합니다.")

choice = st.selectbox("약물 선택", list(DRUGS) + [CUSTOM])
if choice == CUSTOM:
    english = st.text_input("영어 이름 입력", placeholder="예: Naproxen").strip()
    display_ko = None
else:
    english = DRUGS[choice]
    display_ko = choice

if st.button("조회", type="primary"):
    st.session_state["query"] = (display_ko, english)

query = st.session_state.get("query")
if query:
    display_ko, english = query
    if not english:
        st.warning("영어 이름을 입력해 주세요.")
    elif re.search(r"[가-힣]", english):
        # 한글은 PubChem에서 404가 나므로 호출 전에 안내
        st.warning("한글 이름은 검색되지 않습니다. 영어 이름으로 입력해 주세요.")
    else:
        try:
            with st.spinner("PubChem에서 조회 중..."):
                cid = cached_cid(english)
                props = cached_props(cid)
                png = cached_png(cid)
                ghs = cached_ghs(cid)
        except api.PubChemError as e:  # 404, 네트워크 오류, 타임아웃 등
            st.error(str(e))
        except Exception:
            st.error("예상치 못한 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.")
        else:
            # 이름 / CID
            title = f"{display_ko} ({english})" if display_ko else english
            st.header(title)
            st.write(f"**CID:** {cid}")

            # 구조 이미지 + 물성
            col1, col2 = st.columns([1, 2])
            with col1:
                st.image(png, caption="분자 구조 (PubChem)")
            with col2:
                st.subheader("물성")
                st.write(f"**분자식:** {props.get('MolecularFormula', '-')}")
                st.write(f"**분자량:** {props.get('MolecularWeight', '-')} g/mol")
                st.write(f"**XLogP:** {props.get('XLogP', '정보 없음')}")
                st.write(f"**IUPAC 이름:** {props.get('IUPACName', '-')}")
                st.write("**SMILES:**")
                st.code(props.get("SMILES", "-"), language=None)

            # GHS 안전 정보
            st.subheader("GHS 안전 정보")
            if not ghs:
                st.info("안전 분류 정보 없음")
            else:
                if ghs["pictograms"]:
                    cols = st.columns(len(ghs["pictograms"]))
                    for c, p in zip(cols, ghs["pictograms"]):
                        c.image(p["url"], caption=p["label"], width=80)
                if ghs["signal"]:
                    signal_text = ghs["signal"]
                elif any(s.startswith("Not Classified") for s in ghs["statements"]):
                    # 원본이 "Not Classified"인 경우: 위험물 분류 대상이 아니라 신호어가 없는 것
                    signal_text = "없음 (GHS 위험 분류 대상 아님)"
                else:
                    signal_text = "정보 없음"
                st.write(f"**신호어(Signal word):** {signal_text}")
                if ghs["statements"]:
                    st.write("**유해·위험 문구(Hazard statements):**")
                    for s in ghs["statements"]:
                        st.markdown(f"- {s}")
                if ghs["source"]:
                    st.caption(f"GHS 출처: {ghs['source']}")

            st.markdown(f"[PubChem에서 보기]({api.pubchem_url(cid)})")

st.divider()
st.warning("PubChem 정보 기반이며, 실제 복용·취급은 약사/의사 및 공식 문서를 따르세요.")
st.caption("출처: PubChem (https://pubchem.ncbi.nlm.nih.gov)")
