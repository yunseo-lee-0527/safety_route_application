"""
최단 경로(Optimal Path) 계산 Processor — 서울시 전체

각 주거 건물에서 가장 가까운 학교 정문/후문까지의 최단 경로 계산

Input:
  data/raw/school_gate_seoul_*.csv             (학교 정문 위치, 전 서울 자치구)
  data/raw/서울시 자치구별 도보 네트워크 공간정보.csv  (보행 네트워크, cp949, ~100 MB)
  output/seoul_commuting_zone_buildings.gpkg   (주거 건물, 통학구역별 레이어)

Output:
  data/processed/school_paths_optimal.geojson
"""
import re
import json
import shutil
import pandas as pd
import geopandas as gpd
import networkx as nx
import numpy as np
from pathlib import Path
from shapely.geometry import LineString
from shapely.wkt import loads as wkt_loads
from scipy.spatial.distance import cdist
import sys
import logging

sys.path.append(str(Path(__file__).parent.parent))

from config import Paths, get_gate_csv_files
from utils.checkpoint import CheckpointManager
from utils.geojson_writer import GeoJSONWriter

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── CSV column names (보행 네트워크 CSV, cp949) ──────────────────────────────
_COL_TYPE     = '노드링크 유형'
_COL_NODE_WKT = '노드 WKT'
_COL_NODE_ID  = '노드 ID'
_COL_START    = '시작노드 ID'
_COL_END      = '종료노드 ID'
_COL_LENGTH   = '링크 길이'


# ── Helper: gate CSV reader ──────────────────────────────────────────────────

def _read_gate_csv(path) -> pd.DataFrame:
    """Read a gate CSV with automatic encoding and separator detection.

    Encoding priority: utf-8-sig → utf-8 → cp949 → euc-kr
    Separator: detected from the header line (tab or comma).
    """
    with open(path, 'rb') as fh:
        raw = fh.read()

    decoded = None
    used_enc = None
    for enc in ('utf-8-sig', 'utf-8', 'cp949', 'euc-kr'):
        try:
            decoded = raw.decode(enc)
            used_enc = enc
            break
        except (UnicodeDecodeError, LookupError):
            continue

    if decoded is None:
        raise ValueError(f"Cannot decode {path.name}: tried utf-8-sig/utf-8/cp949/euc-kr")

    first_line = decoded.splitlines()[0]
    sep = '\t' if chr(9) in first_line else ','

    return pd.read_csv(path, encoding=used_enc, sep=sep)


# ── Helper: school name normalisation ───────────────────────────────────────

def _school_short_name(full_name: str) -> str:
    """'서울한남초등학교' → '한남초'   /   '신광초등학교' → '신광초'

    Steps:
      1. Strip leading '서울' prefix.
      2. Strip trailing '등학교' (covers both '초등학교' and '등학교').
    """
    if not isinstance(full_name, str):
        return ''
    name = re.sub(r'^서울', '', full_name.strip())
    name = re.sub(r'등학교$', '', name)
    return name.strip()


def _layer_short_name(layer_name: str) -> str:
    """'한남초_res' → '한남초'"""
    return layer_name.replace('_res', '').strip()


# ── Helper: WKT point parser ─────────────────────────────────────────────────

def _parse_wkt_point(wkt_str: str):
    """WKT POINT 문자열 → (lon, lat) tuple, or None on failure."""
    if not isinstance(wkt_str, str) or not wkt_str.strip().upper().startswith('POINT'):
        return None
    try:
        geom = wkt_loads(wkt_str)
        return (geom.x, geom.y)
    except Exception:
        return None


# ── Main processor ───────────────────────────────────────────────────────────

class OptimalPathProcessor:
    """최단 경로 계산 Processor (서울시 전체)"""

    def __init__(self):
        self.network_csv    = Paths.WALKING_NETWORK_CSV
        self.buildings_gpkg = Paths.SEOUL_RESIDENTIAL_BUILDINGS_GPKG
        self.output_geojson = Paths.DATA_PROCESSED / 'school_paths_optimal.geojson'

        # Populated after load_network()
        self.G_main    = None
        self.node_data = {}          # {node_id: (lon, lat)}
        # Precomputed arrays for fast nearest-node lookup
        self._node_ids = []
        self._node_arr = None        # np.ndarray shape (N, 2)

        self.school_gates_valid = None
        self.layer_mapping      = None

    # ── 1. Load gate CSV files ───────────────────────────────────────────────

    def load_school_gates(self) -> pd.DataFrame:
        """모든 자치구의 학교 정문/후문 데이터를 로드하여 병합."""
        csv_files = get_gate_csv_files()
        if not csv_files:
            raise FileNotFoundError(
                f"No school gate CSV files found in {Paths.DATA_RAW}. "
                "Expected pattern: school_gate_seoul_*.csv"
            )
        logger.info(f"Loading {len(csv_files)} gate CSV files ...")

        frames = []
        for csv_path in csv_files:
            try:
                df = _read_gate_csv(csv_path)
                frames.append(df)
                logger.info(f"  {csv_path.name}: {len(df)} rows")
            except Exception as e:
                logger.warning(f"Failed to read {csv_path.name}: {e} -- skipping")

        if not frames:
            raise ValueError("All gate CSV files failed to load.")

        combined = pd.concat(frames, ignore_index=True)
        df_valid = combined[combined['lat'].notna() & combined['lon'].notna()].copy()
        logger.info(f"Valid gates: {len(df_valid)} / {len(combined)}")
        return df_valid

    # ── 2. Load walking network ──────────────────────────────────────────────

    def load_network(self):
        """보행 네트워크 CSV를 읽어 NetworkX 그래프 구축."""
        logger.info(f"Loading walking network from {self.network_csv} ...")

        G         = nx.Graph()
        node_data = {}
        n_nodes = n_links = skipped = 0

        for chunk in pd.read_csv(self.network_csv, encoding='cp949', chunksize=50_000):
            # NODE rows
            node_rows = chunk[chunk[_COL_TYPE] == 'NODE'][[_COL_NODE_ID, _COL_NODE_WKT]].dropna()
            for _, row in node_rows.iterrows():
                pt = _parse_wkt_point(row[_COL_NODE_WKT])
                if pt is None:
                    skipped += 1
                    continue
                nid = str(int(row[_COL_NODE_ID]))  # normalise int64/float64
                node_data[nid] = pt
                G.add_node(nid, lon=pt[0], lat=pt[1])
                n_nodes += 1

            # LINK rows
            link_rows = chunk[chunk[_COL_TYPE] == 'LINK'][[_COL_START, _COL_END, _COL_LENGTH]].dropna()
            for _, row in link_rows.iterrows():
                try:
                    w = float(row[_COL_LENGTH])
                except (ValueError, TypeError):
                    skipped += 1
                    continue
                if w <= 0:
                    skipped += 1
                    continue
                G.add_edge(str(int(row[_COL_START])), str(int(row[_COL_END])), weight=w)  # normalise float64
                n_links += 1

        logger.info(
            f"Nodes: {n_nodes:,}  |  Links: {n_links:,}  |  Skipped: {skipped:,}"
        )
        logger.info(f"Graph: {G.number_of_nodes():,} nodes, {G.number_of_edges():,} edges")

        if G.number_of_nodes() == 0:
            raise RuntimeError("Network graph is empty. Check CSV columns/encoding.")

        largest_cc = max(nx.connected_components(G), key=len)
        G_main = G.subgraph(largest_cc).copy()
        logger.info(
            f"Largest CC: {G_main.number_of_nodes():,} nodes, "
            f"{G_main.number_of_edges():,} edges"
        )

        return G_main, node_data

    # ── 3. Dynamic layer mapping ─────────────────────────────────────────────

    def _build_layer_mapping(self) -> dict:
        """GPKG 레이어명과 학교 정문 학교명을 동적으로 매칭.

        Returns:
            {school_full_name: gpkg_layer_name}
        """
        import fiona

        actual_layers = fiona.listlayers(str(self.buildings_gpkg))
        logger.info(f"GPKG has {len(actual_layers)} layers")

        # layer -> short name lookup
        layer_shorts = {layer: _layer_short_name(layer) for layer in actual_layers}

        gate_schools = self.school_gates_valid['school_name'].dropna().unique()
        mapping = {}

        for school in gate_schools:
            short = _school_short_name(school)
            if not short:
                continue

            # 1) Exact match
            matched = next(
                (layer for layer, lshort in layer_shorts.items() if short == lshort),
                None
            )
            # 2) Partial match (substring)
            if matched is None:
                matched = next(
                    (layer for layer, lshort in layer_shorts.items()
                     if short in lshort or lshort in short),
                    None
                )

            if matched:
                mapping[school] = matched
                logger.info(f"  Matched: '{school}' -> '{matched}'")
            else:
                logger.debug(f"  No layer for school: '{school}' (short: '{short}')")

        logger.info(f"Layer mapping: {len(mapping)} schools matched")
        return mapping

    # ── 4. Nearest-node lookup (vectorised) ─────────────────────────────────

    def _precompute_node_arrays(self):
        """node_data 딕셔너리를 정렬된 배열로 미리 변환 (빠른 nearest-node 조회용)."""
        self._node_ids = list(self.node_data.keys())
        self._node_arr = np.array(list(self.node_data.values()), dtype=float)
        # 서울 위도(~37.55°)에서 경도 보정 계수 사전 계산
        # 1° lon ≈ 88km vs 1° lat ≈ 111km → 보정 없이 cdist 쓰면 잘못된 노드 선택 가능
        self._cos_lat = np.cos(np.radians(37.55))
        self._node_arr_scaled = self._node_arr.copy()
        self._node_arr_scaled[:, 0] *= self._cos_lat

    def find_nearest_node(self, point_coords):
        """가장 가까운 네트워크 노드 찾기 (cos(lat) 보정 거리 사용)."""
        if self._node_arr is None or len(self._node_arr) == 0:
            return None, float('inf')
        scaled_point = np.array([[point_coords[0] * self._cos_lat, point_coords[1]]])
        distances = cdist(scaled_point, self._node_arr_scaled)[0]
        nearest   = int(np.argmin(distances))
        return self._node_ids[nearest], float(distances[nearest])

    # ── 5. Compute paths ─────────────────────────────────────────────────────

    def compute_paths(self) -> list:
        """모든 건물에서 학교 정문까지 최단 경로 계산 (중단 후 재시작 가능).

        체크포인트: output/.checkpoints/optimal_paths/
          done.json     -- 완료된 학교명 목록
          school_*.json -- 학교별 경로 결과
        """
        logger.info("=" * 60)
        logger.info("Computing optimal paths ...")
        logger.info("=" * 60)

        self.layer_mapping = self._build_layer_mapping()
        if not self.layer_mapping:
            raise RuntimeError("No layer mapping found. Check GPKG file and gate CSVs.")

        logger.info("Computing nearest network nodes for school gates ...")
        self.school_gates_valid['nearest_node'] = self.school_gates_valid.apply(
            lambda row: self.find_nearest_node((row['lon'], row['lat']))[0],
            axis=1
        )

        import fiona
        gpkg_layers = set(fiona.listlayers(str(self.buildings_gpkg)))

        # Checkpoint setup
        ckpt_dir = Paths.SEOUL_COMMUTING_ZONES_GPKG.parent / ".checkpoints" / "optimal_paths"
        ckpt_dir.mkdir(parents=True, exist_ok=True)
        ckpt = CheckpointManager(ckpt_dir / "done.json")

        # Load partial results from a previous interrupted run
        all_paths = []
        for partial_file in sorted(ckpt_dir.glob("school_*.json")):
            try:
                with open(partial_file, encoding="utf-8") as pf:
                    data = json.load(pf)
                for feat in data.get("features", []):
                    props = feat["properties"]
                    coords = feat["geometry"]["coordinates"]
                    all_paths.append({
                        "school":   props["school"],
                        "gate":     props["gate"],
                        "distance": props["distance"],
                        "geometry": LineString(coords),
                    })
            except Exception as load_err:
                logger.warning(f"Could not load partial file {partial_file.name}: {load_err}")

        if ckpt.count() > 0:
            logger.info(
                f"Resuming: {ckpt.count()} schools already done, "
                f"{len(all_paths)} paths loaded from checkpoints"
            )

        for school, layer_name in self.layer_mapping.items():
            if ckpt.is_done(school):
                logger.info(f"  Skipping {school} (checkpoint)")
                continue

            logger.info(f"Processing {school} ...")
            if layer_name not in gpkg_layers:
                logger.warning(f"  Layer {layer_name!r} not in GPKG, skipping")
                continue

            try:
                gdf_buildings = gpd.read_file(self.buildings_gpkg, layer=layer_name)
                logger.info(f"  Buildings: {len(gdf_buildings)}")
                if gdf_buildings.crs and gdf_buildings.crs.to_epsg() != 4326:
                    gdf_buildings = gdf_buildings.to_crs(epsg=4326)
                gdf_buildings = gdf_buildings.copy()
                gdf_buildings['centroid'] = gdf_buildings.geometry.centroid

                gates_df = self.school_gates_valid[self.school_gates_valid['school_name'] == school]
                if gates_df.empty:
                    logger.warning(f"  No gates found for {school}")
                    ckpt.mark_done(school)
                    continue

                gates = gates_df.to_dict('records')
                logger.info(f"  Gates: {len(gates)}")

                # 게이트 노드에서 Dijkstra 1회 실행 → 모든 건물 거리/경로를 한꺼번에 조회
                # 기존: O(buildings * gates) Dijkstra → 변경: O(gates) Dijkstra (대폭 개선)
                gate_results = []  # [(gate_dict, distances, paths)]
                for gate in gates:
                    dest_node = gate.get('nearest_node')
                    if not dest_node or dest_node not in self.G_main:
                        continue
                    try:
                        distances, paths = nx.single_source_dijkstra(
                            self.G_main, dest_node, weight='weight', cutoff=10000
                        )
                        gate_results.append((gate, distances, paths))
                    except Exception:
                        continue

                if not gate_results:
                    logger.warning(f"  No valid gate nodes for {school}")
                    ckpt.mark_done(school)
                    continue

                school_paths = []
                for _, building in gdf_buildings.iterrows():
                    origin_node, _ = self.find_nearest_node((building['centroid'].x, building['centroid'].y))
                    if not origin_node or origin_node not in self.G_main:
                        continue
                    best_path, best_length, best_gate_type = None, float('inf'), None
                    for gate, distances, paths in gate_results:
                        if origin_node in distances and distances[origin_node] < best_length:
                            best_length    = distances[origin_node]
                            best_path      = paths[origin_node]
                            best_gate_type = gate.get('gate_type')
                    if best_path and best_length < float('inf'):
                        # 경로 방향 반전: gate→building → building→gate
                        coords = [self.node_data[n] for n in reversed(best_path) if n in self.node_data]
                        if len(coords) > 1:
                            school_paths.append({'school': school, 'gate': best_gate_type,
                                                  'distance': best_length, 'geometry': LineString(coords)})

                # Save checkpoint for this school
                safe_name = re.sub(r'[^\w가-힣]', '_', school)
                partial_path = ckpt_dir / f"school_{safe_name}.json"
                features = [GeoJSONWriter.feature(p['geometry'],
                    {'school': p['school'], 'gate': p['gate'], 'distance': round(float(p['distance']), 2)})
                    for p in school_paths]
                with open(partial_path, 'w', encoding='utf-8') as pf:
                    json.dump({'type': 'FeatureCollection', 'features': features}, pf, ensure_ascii=False)
                ckpt.mark_done(school)
                all_paths.extend(school_paths)
                logger.info(f"  {len(school_paths)} paths saved (checkpoint)")

            except Exception as e:
                logger.error(f"Failed to process {school}: {e}")
                import traceback
                traceback.print_exc()
                continue

        logger.info(f"Total paths computed: {len(all_paths)}")

        # Clean up checkpoints after full completion
        shutil.rmtree(ckpt_dir, ignore_errors=True)
        logger.info("Checkpoints cleaned up")
        return all_paths

    def save_geojson(self, paths: list):
        """GeoJSON 저장."""
        logger.info(f"Saving {len(paths)} paths to {self.output_geojson} ...")

        features = []
        for p in paths:
            props = {
                'school':   p['school'],
                'gate':     p['gate'],
                'distance': round(float(p['distance']), 2),
            }
            features.append(GeoJSONWriter.feature(p['geometry'], props))

        self.output_geojson.parent.mkdir(parents=True, exist_ok=True)
        GeoJSONWriter.write(features, self.output_geojson)

        import shutil
        web_dst = Paths.WEB_DATA / self.output_geojson.name
        web_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.output_geojson, web_dst)
        logger.info(f"Copied to {web_dst}")

        distances = [p['distance'] for p in paths]
        logger.info(
            f"Distance stats: mean={np.mean(distances):.2f}m  "
            f"min={np.min(distances):.2f}m  max={np.max(distances):.2f}m"
        )
        logger.info(f"Saved -> {self.output_geojson}")

    # ── 7. Full pipeline ─────────────────────────────────────────────────────

    def run(self) -> bool:
        """전체 파이프라인 실행."""
        logger.info("=" * 60)
        logger.info("Optimal Path Processor (Seoul-wide)")
        logger.info("=" * 60)

        try:
            self.school_gates_valid     = self.load_school_gates()
            self.G_main, self.node_data = self.load_network()
            self._precompute_node_arrays()

            paths = self.compute_paths()
            if not paths:
                raise RuntimeError("No paths computed. Check input data.")

            self.save_geojson(paths)

            logger.info("=" * 60)
            logger.info("Processing completed successfully")
            logger.info("=" * 60)
            return True

        except Exception as e:
            logger.error(f"Processing failed: {e}")
            import traceback
            traceback.print_exc()
            return False


if __name__ == '__main__':
    processor = OptimalPathProcessor()
    success = processor.run()
    if not success:
        sys.exit(1)
