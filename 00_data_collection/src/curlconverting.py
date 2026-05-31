"""
curlconverting.py
-----------------
End-to-end pipeline:
  curl_command.txt -> taas_response.json -> taas_accidents_with_latlon.csv
                  -> seoul_link_with_accidents.csv  (LINK_ID 단위 사고 집계)

사용법:
  1) Chrome DevTools(F12) -> Network -> 해당 요청 우클릭 -> Copy -> Copy as cURL (bash)
  2) `curl_command.txt` 파일에 그대로 붙여넣기 (다중행 OK)
  3) `python curlconverting.py` 실행

처음 실행 시 curl_command.txt가 없으면 템플릿이 자동 생성됩니다.
"""

import os
os.environ["SHAPE_RESTORE_SHX"] = "YES"   # SHP의 누락된 .shx 자동 복원

import json
import shlex
import sys
import time
from pathlib import Path

import requests
import pandas as pd
import geopandas as gpd
from pyproj import Transformer
from shapely.geometry import Point

# ── 경로 ──────────────────────────────────────────────────────────────────────
BASE_DIR           = Path(__file__).resolve().parent
CURL_FILE          = BASE_DIR / "curl_command.txt"
RESPONSE_JSON      = BASE_DIR / "taas_response.json"
BATCH_DIR          = BASE_DIR / "batches"   # 자치구별 응답 캐시
ACC_CSV            = BASE_DIR / "taas_accidents_with_latlon.csv"
LINK_SHP           = BASE_DIR / "node_link_data" / "MOCT_LINK.shp"
BOUNDARY_SHP = BASE_DIR / "seoul_boundary.shp"   # 서울(또는 관악구) 행정경계 SHP (사용자 준비)
OUT_LINK     = BASE_DIR / "gwanak_link_with_accidents.csv"

WORK_CRS = "EPSG:5186"   # MOCT_LINK 한국 TM(중부원점)
TAAS_CRS = "EPSG:5179"   # TAAS 응답의 x_crdnt/y_crdnt 좌표계

# ── batch / 재시도 설정 ───────────────────────────────────────────────────────
SEOUL_GU_CODES = [
    ("11620", "관악구"),
]
REQUEST_TIMEOUT     = 90    # 초 — 단일 요청 타임아웃
MAX_RETRIES         = 4     # 타임아웃/끊김 시 재시도 횟수
RETRY_BASE_WAIT     = 3     # 초 — 백오프 기준 (3, 6, 12, 24)
INTER_REQUEST_DELAY = 0.5   # 초 — 성공 요청 사이 간격 (서버 부하 완화)


# ── curl(bash) 파서 ──────────────────────────────────────────────────────────
NO_ARG_FLAGS = {
    "--compressed", "-k", "--insecure", "-L", "--location",
    "-s", "--silent", "-i", "--include", "-v", "--verbose",
    "-f", "--fail", "-#", "--progress-bar",
    "--http1.0", "--http1.1", "--http2", "--http2-prior-knowledge",
    "--tlsv1.2", "--tlsv1.3", "-O", "--remote-name",
    "-J", "--remote-header-name", "-g", "--globoff",
}

def parse_curl_bash(cmd: str) -> dict:
    # bash 줄 연속 `\<newline>` -> 공백
    cmd = cmd.replace("\\\r\n", " ").replace("\\\n", " ")
    tokens = shlex.split(cmd, posix=True)
    if not tokens:
        raise ValueError("빈 curl 명령")
    if tokens[0].lower() != "curl":
        raise ValueError(f"'curl'로 시작해야 합니다. 받은 첫 토큰: {tokens[0]!r}")

    url, method, data = None, None, None
    headers, cookies = {}, {}

    i = 1
    while i < len(tokens):
        t = tokens[i]
        if t in ("-H", "--header"):
            i += 1
            name, _, value = tokens[i].partition(":")
            headers[name.strip()] = value.strip()
        elif t in ("-b", "--cookie"):
            i += 1
            for pair in tokens[i].split(";"):
                pair = pair.strip()
                if "=" in pair:
                    k, _, v = pair.partition("=")
                    cookies[k.strip()] = v.strip()
        elif t in ("-X", "--request"):
            i += 1
            method = tokens[i]
        elif t in ("-d", "--data", "--data-raw", "--data-binary",
                   "--data-ascii", "--data-urlencode"):
            i += 1
            data = tokens[i]
        elif t == "--url":
            i += 1
            url = tokens[i]
        elif t in ("-A", "--user-agent"):
            i += 1
            headers["User-Agent"] = tokens[i]
        elif t in ("-e", "--referer"):
            i += 1
            headers["Referer"] = tokens[i]
        elif t in NO_ARG_FLAGS:
            pass
        elif t.startswith("-"):
            # 알 수 없는 인자 — 안전하게 다음 토큰을 인자로 간주해 건너뜀
            i += 1
        else:
            if url is None:
                url = t
        i += 1

    if method is None:
        method = "POST" if data is not None else "GET"
    if url is None:
        raise ValueError("URL을 찾지 못했습니다")
    return {"url": url, "method": method, "headers": headers,
            "cookies": cookies, "data": data}


CURL_TEMPLATE = """# 이 파일에 Chrome DevTools에서 복사한 curl 명령(bash)을 붙여넣으세요.
# 방법:
#   F12 -> Network 탭 -> selectAccidentInfo.do 요청 우클릭
#   -> Copy -> Copy as cURL (bash)
# 그리고 이 # 안내 줄들은 지운 뒤 저장하세요.
#
# 예:
# curl 'https://taas.koroad.or.kr/...' \\
#   -H 'Cookie: TAASJSESSIONID=...' \\
#   -H 'X-CSRF-TOKEN: ...' \\
#   --data-raw '{"startAcdntYear":"2019",...}'
"""


# ── Step 1: curl_command.txt -> 자치구별 batch 요청 -> taas_response.json ─────
def _log(msg: str) -> None:
    print(msg, flush=True)


def request_with_retry(parsed: dict, body: dict, prefix: str):
    """타임아웃/끊김 시 지수 백오프로 재시도. 성공 시 dict, 실패 시 None.
    세션/CSRF 만료(HTTP 500 + HTML 응답)는 재시도 무의미하므로 즉시 sys.exit."""
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.request(
                parsed["method"], parsed["url"],
                headers=parsed["headers"],
                cookies=parsed["cookies"],
                json=body,
                timeout=REQUEST_TIMEOUT,
            )
            ctype = r.headers.get("Content-Type", "")
            if r.status_code == 200 and "application/json" in ctype:
                return r.json()

            # 세션 만료로 보이는 비정상 응답
            if r.status_code in (401, 403) or (
                r.status_code == 500 and "<html" in r.text[:500].lower()
            ):
                _log(f"{prefix} ! HTTP {r.status_code} — TAAS 세션/CSRF 만료로 보입니다.")
                _log(f"{prefix}   브라우저에서 새로고침 후 'Copy as cURL (bash)'을 다시 받아")
                _log(f"{prefix}   {CURL_FILE.name}을 갱신한 뒤 재실행하세요.")
                sys.exit(1)

            last_err = f"HTTP {r.status_code} / {ctype}"
            _log(f"{prefix} ! {last_err} (시도 {attempt}/{MAX_RETRIES})")
        except (requests.Timeout, requests.ConnectionError) as e:
            last_err = f"{type(e).__name__}: {e}"
            _log(f"{prefix} ! {last_err} (시도 {attempt}/{MAX_RETRIES})")
        except requests.RequestException as e:
            last_err = f"{type(e).__name__}: {e}"
            _log(f"{prefix} ! {last_err} (시도 {attempt}/{MAX_RETRIES})")

        if attempt < MAX_RETRIES:
            wait = RETRY_BASE_WAIT * (2 ** (attempt - 1))
            _log(f"{prefix}   {wait}s 대기 후 재시도")
            time.sleep(wait)

    _log(f"{prefix} XX 최종 실패: {last_err}")
    return None


def fetch_one_gu(parsed: dict, base_body: dict, gu_code: str, prefix: str):
    """단일 자치구에 대해 전체 사고 레코드 수집.

    TAAS API는 pageIndex를 무시하고 매 요청마다 동일한 전체 결과를 반환하므로
    먼저 page 1로 총 건수를 파악한 뒤, recordCountPerPage를 총 건수로 맞춰
    단 1회 요청으로 전체를 가져온다.
    """
    body = dict(base_body)
    body["legaldongCode"] = gu_code + "%"
    body["pageIndex"] = 1

    # ── 1차 요청: 총 건수 파악 ────────────────────────────────────────────────
    data = request_with_retry(parsed, body, prefix)
    if data is None:
        return None

    rv = data.get("resultValue") or {}
    pagination = rv.get("paginationInfo") or {}
    total = pagination.get("totalRecordCount") or 0
    records = rv.get("accidentInfoList") or []

    # 이미 전체 수신 완료된 경우 그대로 반환
    if total == 0 or len(records) >= total:
        _log(f"{prefix}   단일 응답으로 {len(records):,}건 수신 완료")
        return {"resultValue": {"accidentInfoList": records, "paginationInfo": pagination}}

    # ── 2차 요청: recordCountPerPage=total 로 한 번에 전체 수신 ──────────────
    _log(f"{prefix}   총 {total:,}건 — recordCountPerPage={total}로 재요청")
    body["recordCountPerPage"] = total
    body["pageUnit"] = 1
    body["pageIndex"] = 1

    data2 = request_with_retry(parsed, body, prefix)
    if data2 is None:
        _log(f"{prefix}   재요청 실패 — 1차 결과({len(records):,}건)만 사용")
        return {"resultValue": {"accidentInfoList": records, "paginationInfo": pagination}}

    rv2 = data2.get("resultValue") or {}
    records2 = rv2.get("accidentInfoList") or []
    pagination2 = rv2.get("paginationInfo") or pagination

    _log(f"{prefix}   {len(records2):,}건 수신 완료 (예상 {total:,}건)")
    return {"resultValue": {"accidentInfoList": records2, "paginationInfo": pagination2}}


def step1_fetch() -> dict:
    _log("[1/3] curl 파싱 + 관악구 batch 요청")
    if not CURL_FILE.exists():
        CURL_FILE.write_text(CURL_TEMPLATE, encoding="utf-8")
        sys.exit(f"  -> {CURL_FILE.name} 템플릿을 생성했습니다. "
                 "Chrome DevTools에서 'Copy as cURL (bash)'으로 복사한 명령을 "
                 "이 파일에 붙여넣고 다시 실행하세요.")

    raw_text = CURL_FILE.read_text(encoding="utf-8")
    cmd = "\n".join(
        line for line in raw_text.splitlines()
        if not line.lstrip().startswith("#")
    ).strip()
    if not cmd:
        sys.exit(f"  X {CURL_FILE.name}이 비어 있습니다.")

    parsed = parse_curl_bash(cmd)
    if not parsed["data"]:
        sys.exit("  X curl 명령에 요청 본문(--data-raw)이 없습니다.")
    try:
        base_body = json.loads(parsed["data"])
    except json.JSONDecodeError:
        sys.exit("  X 요청 본문을 JSON으로 파싱할 수 없습니다.")

    _log(f"  - {parsed['method']} {parsed['url']}")
    _log(f"  - 기본 파라미터: {base_body}")
    _log(f"  - batch 결과 저장 폴더: {BATCH_DIR.name}/  (재실행 시 캐시 사용)")

    BATCH_DIR.mkdir(exist_ok=True)

    n = len(SEOUL_GU_CODES)
    all_records: list = []
    succeeded: list = []
    failed: list = []
    cached: list = []

    t_start = time.time()
    for i, (gu_code, gu_name) in enumerate(SEOUL_GU_CODES, 1):
        prefix = f"  [{i:2d}/{n}] {gu_name}({gu_code})"
        batch_file = BATCH_DIR / f"taas_{gu_code}.json"

        if batch_file.exists():
            try:
                data = json.loads(batch_file.read_text(encoding="utf-8"))
                recs = (data.get("resultValue") or {}).get("accidentInfoList") or []
                _log(f"{prefix} 캐시 사용 — {len(recs):,}건  ({batch_file.name})")
                all_records.extend(recs)
                cached.append((gu_code, gu_name))
                continue
            except (json.JSONDecodeError, OSError) as e:
                _log(f"{prefix} ! 캐시 읽기 실패 ({e}) — 재요청")

        _log(f"{prefix} 요청 시작...")
        t0 = time.time()
        data = fetch_one_gu(parsed, base_body, gu_code, prefix)
        elapsed = time.time() - t0

        if data is None:
            failed.append((gu_code, gu_name))
            continue

        # 디스크에 저장 — 사용자가 직접 열어 검증 가능
        batch_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        recs = (data.get("resultValue") or {}).get("accidentInfoList") or []
        all_records.extend(recs)
        succeeded.append((gu_code, gu_name))
        _log(f"{prefix} 완료 — {len(recs):,}건  ({elapsed:.1f}s)  → {batch_file.name}")
        _log(f"            누적 {len(all_records):,}건 / 진행 {i}/{n} ({i/n*100:.0f}%)")
        time.sleep(INTER_REQUEST_DELAY)

    elapsed_total = time.time() - t_start

    # 모든 batch 통합본을 단일 JSON으로 저장
    combined = {"resultValue": {"accidentInfoList": all_records}}
    RESPONSE_JSON.write_text(
        json.dumps(combined, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    _log("")
    _log(f"  [요약] 총 소요 {elapsed_total:.1f}s")
    _log(f"    신규 성공 {len(succeeded)} / 캐시 {len(cached)} / 실패 {len(failed)} / 합계 {n}")
    _log(f"    수집 사고 레코드: {len(all_records):,}건")
    if failed:
        _log("    실패 batch (다시 실행하면 자동 재시도):")
        for gu_code, gu_name in failed:
            _log(f"      - {gu_name}({gu_code})")
        _log(f"  ! 실패가 있어 step2/3 진행 전 한 번 더 실행을 권장합니다.")
    _log(f"  -> 저장: {RESPONSE_JSON.name}")
    return combined


# ── Step 2: JSON -> 사고 lat/lon CSV ──────────────────────────────────────────
def _find_record_list(obj, depth: int = 0):
    candidates = ["accidentInfoList", "resultList", "list", "data", "rows", "items"]
    if depth > 4:
        return None
    if isinstance(obj, dict):
        for k in candidates:
            v = obj.get(k)
            if isinstance(v, list) and v and isinstance(v[0], dict):
                return v
        for v in obj.values():
            r = _find_record_list(v, depth + 1)
            if r is not None:
                return r
    return None


def step2_convert(raw: dict) -> pd.DataFrame:
    print("[2/3] JSON -> 사고 lat/lon CSV")
    records = _find_record_list(raw)
    if records is None:
        sys.exit("  X 사고 레코드 리스트를 응답에서 찾지 못했습니다.")
    df = pd.DataFrame(records)
    print(f"  - 레코드 수: {len(df):,}")

    if "x_crdnt" not in df.columns or "y_crdnt" not in df.columns:
        sys.exit("  X x_crdnt/y_crdnt 컬럼이 없습니다.")

    has = (df["x_crdnt"].notna() & df["y_crdnt"].notna() &
           (df["x_crdnt"] != 0) & (df["y_crdnt"] != 0))
    df = df[has].copy()

    tr = Transformer.from_crs(TAAS_CRS, "EPSG:4326", always_xy=True)
    lons, lats = tr.transform(df["x_crdnt"].to_numpy(), df["y_crdnt"].to_numpy())
    df["lon"] = lons
    df["lat"] = lats

    df.to_csv(ACC_CSV, index=False, encoding="utf-8-sig")
    print(f"  - 좌표 유효 레코드: {len(df):,}건")
    print(f"  -> 저장: {ACC_CSV.name}")
    return df


# ── Step 3: 사고점 -> MOCT_LINK 최근접 매칭 + LINK 단위 집계 ───────────────────
GWANAK_CODE = "11620"
GWANAK_NAME = "관악구"


def step3_link_join(df_acc: pd.DataFrame):
    print("[3/3] 사고점 -> MOCT_LINK 최근접 매칭 + LINK 단위 집계")
    if not BOUNDARY_SHP.exists():
        sys.exit(f"  X 행정경계 SHP가 없습니다: {BOUNDARY_SHP.name}")

    gdf_boundary = gpd.read_file(BOUNDARY_SHP).to_crs(WORK_CRS)

    # SHP 내에서 관악구만 추출 (코드 또는 이름 컬럼으로 탐색)
    for col in gdf_boundary.columns:
        vals = gdf_boundary[col].astype(str)
        if vals.str.contains(GWANAK_CODE).any():
            gdf_boundary = gdf_boundary[vals.str.contains(GWANAK_CODE)].copy()
            print(f"  - 관악구 필터링 완료 (컬럼 {col!r}, 코드 {GWANAK_CODE})")
            break
        if vals.str.contains(GWANAK_NAME).any():
            gdf_boundary = gdf_boundary[vals.str.contains(GWANAK_NAME)].copy()
            print(f"  - 관악구 필터링 완료 (컬럼 {col!r}, 이름 {GWANAK_NAME!r})")
            break
    else:
        print("  ! 관악구 코드/이름 컬럼을 찾지 못해 SHP 전체 범위를 사용합니다.")

    bbox = tuple(gdf_boundary.total_bounds)
    gwanak_union = gdf_boundary.geometry.union_all()

    gdf_link = gpd.read_file(LINK_SHP, bbox=bbox).set_crs(WORK_CRS, allow_override=True)
    print(f"  - 관악구 bbox 내 LINK: {len(gdf_link):,}")

    gdf_link = gdf_link[gdf_link.geometry.intersects(gwanak_union)].copy()
    print(f"  - 관악구 경계 내 LINK: {len(gdf_link):,}")

    gdf_acc = gpd.GeoDataFrame(
        df_acc[["acdnt_no", "lon", "lat"]],
        geometry=[Point(x, y) for x, y in zip(df_acc["lon"], df_acc["lat"])],
        crs="EPSG:4326",
    ).to_crs(WORK_CRS)

    gdf_acc = gdf_acc[gdf_acc.geometry.within(gwanak_union)].copy()
    print(f"  - 관악구 경계 내 사고: {len(gdf_acc):,}")

    joined = gpd.sjoin_nearest(
        gdf_acc[["acdnt_no", "geometry"]],
        gdf_link[["LINK_ID", "geometry"]],
        how="left", distance_col="dist_m",
    ).sort_values("dist_m").drop_duplicates(subset="acdnt_no")

    acc_per_link = (
        joined.groupby("LINK_ID").size()
              .reset_index(name="accident_count")
    )

    link_cols = ["LINK_ID", "ROAD_NAME", "ROAD_RANK", "LENGTH"]
    link_cols = [c for c in link_cols if c in gdf_link.columns]
    out = (
        gdf_link[link_cols]
        .drop_duplicates(subset="LINK_ID")
        .merge(acc_per_link, on="LINK_ID", how="left")
    )
    out["accident_count"] = out["accident_count"].fillna(0).astype(int)
    out = out.sort_values("accident_count", ascending=False)

    out.to_csv(OUT_LINK, index=False, encoding="utf-8-sig")
    print(f"  -> 저장: {OUT_LINK.name} ({len(out):,}행)")

    print("\n[요약]")
    print(f"  관악구 경계 내 LINK 수   : {len(out):,}")
    print(f"  사고가 매핑된 LINK 수    : {(out['accident_count'] > 0).sum():,}")
    print(f"  총 사고 수               : {out['accident_count'].sum():,}")


if __name__ == "__main__":
    raw = step1_fetch()
    df_acc = step2_convert(raw)
    step3_link_join(df_acc)
    print("\n[DONE]")
