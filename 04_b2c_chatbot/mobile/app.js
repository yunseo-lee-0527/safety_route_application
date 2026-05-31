// ===== 더미 데이터 =====
// 실제로는 백엔드(route_finder.py)에서 받아올 데이터
const DUMMY_ROUTE = {
  origin: "신림동 1605 인근",
  destination: "봉천초등학교",
  distance_m: 820,
  duration_min: 14,
  school_zone_ratio: 0.62,
  segments: {
    safe: 9, warn: 2, danger: 1, total: 12,
    safe_m: 540, warn_m: 200, danger_m: 80, total_m: 820,
  },
  risky_roads: [
    {
      level: "danger",
      name: "남부순환로",
      safety_index: 1.42,
      description:
        "차량 통행이 많고 횡단보도 신호 주기가 짧아요. 상위 30% 위험 도로지만 이번 경로는 30m만 횡단해요",
      tags: [
        { icon: "ti-car", label: "차량 많음" },
        { icon: "ti-traffic-lights", label: "신호 짧음" },
      ],
    },
    {
      level: "warn",
      name: "신림로 6길",
      safety_index: 0.34,
      description: "좁은 도로에 인도가 없는 구간이에요. 차량 통행 시 한쪽으로 비켜서세요",
      tags: [{ icon: "ti-road-off", label: "인도 없음" }],
    },
    {
      level: "warn",
      name: "봉천로 22길 입구",
      safety_index: 0.18,
      description: "스쿨존이지만 등하교 시간대 차량이 많아요",
      tags: [{ icon: "ti-school", label: "스쿨존" }],
    },
  ],
};

const SAVED_ROUTES = [
  {
    icon: "ti-school",
    name: "집 → 봉천초등학교",
    meta: "평소 14분 · 마지막 사용 어제",
  },
  {
    icon: "ti-building-store",
    name: "학원 → 집",
    meta: "평소 9분",
  },
];

// ===== 백엔드 API =====
// FastAPI 서버 주소. 같은 호스트의 8001 포트를 기본값으로 (정적서버=8000, API=8001).
// 배포 시 이 값만 바꾸면 됩니다.
// Windows에서 "localhost"는 IPv6 ::1 로 먼저 해석돼, IPv4만 듣는 서버에 붙을 때
// 매 요청 ~2초씩 지연된다(연결 폴백 대기). localhost/::1 는 127.0.0.1 로 바꿔서 회피.
const _apiHost = (() => {
  const h = location.hostname;
  if (!h || h === "localhost" || h === "::1" || h === "[::1]") return "127.0.0.1";
  return h;
})();
const API_BASE = window.API_BASE || `http://${_apiHost}:8001`;
const VWORLD_KEY = "B83D87DA-2F4F-3E26-8CF6-51CB281601A6";

// status === 0 → 네트워크/서버 다운 (연결 자체 실패)
// status >= 400 → 서버는 정상, 입력/위치 문제 (422 등) — 메시지가 사용자 안내용
class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function detailMessage(data, status) {
  const d = data && data.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d) && d.length) return d[0].msg || "입력값을 확인해주세요.";
  return `요청 실패 (${status})`;
}

async function apiPost(path, body) {
  let res;
  try {
    res = await fetch(API_BASE + path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch (e) {
    throw new ApiError("잠시 서버에 연결하지 못했어요. 데모 경로를 보여드려요.", 0);
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(detailMessage(data, res.status), res.status);
  return data;
}

async function apiGet(path) {
  let res;
  try {
    res = await fetch(API_BASE + path);
  } catch (e) {
    throw new ApiError("서버에 연결할 수 없어요.", 0);
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(detailMessage(data, res.status), res.status);
  return data;
}

// 브라우저 위치 → {lat, lon}. 권한 거부/실패 시 reject.
function getCurrentPosition() {
  return new Promise((resolve, reject) => {
    if (!navigator.geolocation) return reject(new Error("이 기기는 위치를 지원하지 않아요."));
    navigator.geolocation.getCurrentPosition(
      (p) => resolve({ lat: p.coords.latitude, lon: p.coords.longitude }),
      (e) => reject(new Error(e.code === 1 ? "위치 권한이 거부됐어요." : "위치를 가져오지 못했어요.")),
      { enableHighAccuracy: true, timeout: 8000, maximumAge: 60000 }
    );
  });
}

function addressQueryVariants(raw) {
  const q = raw.trim().replace(/\s+/g, " ");
  const variants = [q];
  const withoutDong = q
    .replace(/\s+\d{1,4}\s*동(\s+\d{1,4}\s*호)?$/u, "")
    .replace(/\s+\d{1,4}\s*동.*$/u, "")
    .trim();
  if (withoutDong && withoutDong !== q) variants.push(withoutDong);
  if (!/^서울|^관악구/.test(q)) variants.push(`서울 관악구 ${q}`);
  return [...new Set(variants.filter(Boolean))];
}

async function vworldSearch(query, type, category) {
  const url = new URL("https://api.vworld.kr/req/search");
  url.searchParams.set("service", "search");
  url.searchParams.set("request", "search");
  url.searchParams.set("version", "2.0");
  url.searchParams.set("crs", "EPSG:4326");
  url.searchParams.set("size", "5");
  url.searchParams.set("page", "1");
  url.searchParams.set("format", "json");
  url.searchParams.set("query", query);
  url.searchParams.set("type", type);
  if (category) url.searchParams.set("category", category);
  url.searchParams.set("key", VWORLD_KEY);
  const data = await jsonp(url);
  return data.response?.result?.items || [];
}

function jsonp(url, timeoutMs = 7000) {
  return new Promise((resolve, reject) => {
    const cb = `__vworld_cb_${Date.now()}_${Math.random().toString(36).slice(2)}`;
    const script = document.createElement("script");
    let timer;
    window[cb] = (data) => {
      clearTimeout(timer);
      delete window[cb];
      script.remove();
      resolve(data || {});
    };
    timer = setTimeout(() => {
      delete window[cb];
      script.remove();
      reject(new Error("주소 검색 시간이 초과됐어요."));
    }, timeoutMs);
    url.searchParams.set("callback", cb);
    script.onerror = () => {
      clearTimeout(timer);
      delete window[cb];
      script.remove();
      reject(new Error("주소 검색 요청에 실패했어요."));
    };
    script.src = url.toString();
    document.head.appendChild(script);
  });
}

async function geocodeOriginQuery(raw) {
  const variants = addressQueryVariants(raw);
  const searches = [
    ["ADDRESS", "ROAD"],
    ["ADDRESS", "PARCEL"],
    ["PLACE", ""],
  ];
  for (const query of variants) {
    for (const [type, category] of searches) {
      const items = await vworldSearch(query, type, category);
      const item = items[0];
      if (!item || !item.point) continue;
      const lat = Number(item.point.y);
      const lon = Number(item.point.x);
      if (!Number.isFinite(lat) || !Number.isFinite(lon)) continue;
      return {
        lat,
        lon,
        title: item.title || query,
        address: item.address?.road || item.address?.parcel || item.address || query,
        exact: query === raw.trim(),
      };
    }
  }
  return null;
}

// 학년 → 기본 스타일 (1~3학년 안전 우선, 4학년 이상도 일단 안전 기본)
function styleForGrade(grade) {
  return grade <= 3 ? "safe" : "safe";
}

// ===== 프로필 (localStorage) =====
const PROFILE_KEY = "safe_route_profile";

function loadProfile() {
  try {
    const raw = localStorage.getItem(PROFILE_KEY);
    if (raw) {
      const p = JSON.parse(raw);
      if (p.grade >= 1 && p.grade <= 6) state.grade = p.grade;
      state.style = state.grade <= 3 ? "safe" : p.style === "fast" ? "fast" : "safe";
      state.baseStyle = state.style;
      if (typeof p.childName === "string" && p.childName.trim()) state.childName = p.childName.trim();
      state.role = p.role === "child" ? "child" : "parent";
      state.profileSet = true;
      return;
    }
  } catch (e) {
    /* 비공개 모드 등 — 온보딩으로 진행 */
  }
  // 미설정 → 첫 화면을 프로필 설정으로
  state.profileSet = false;
  state.currentScreen = "profile";
  state.history = ["profile"];
}

function saveProfile() {
  try {
    localStorage.setItem(
      PROFILE_KEY,
      JSON.stringify({ grade: state.grade, style: state.style, childName: state.childName, role: state.role })
    );
  } catch (e) {
    /* 저장 실패해도 세션 내에서는 동작 */
  }
}

// 도착 학교 전체 목록 로드 (드롭다운용). 서버 없으면 조용히 무시.
async function loadSchools() {
  if (state.schools.length) return;
  try {
    const list = await apiGet("/api/schools");
    state.schools = list.map((s) => s.name).sort((a, b) => a.localeCompare(b, "ko"));
    state.schoolGates = {};
    list.forEach((s) => { state.schoolGates[s.name] = s.gates || []; });
    if (state.currentScreen === "input") render();
  } catch (e) {
    /* 백엔드 미기동: 드롭다운은 자동 추천만 */
  }
}

// 출발 좌표 → 학구 자동 도착지 해석. 출발지 바뀌면 선택값을 학구 기준으로 리셋.
async function resolveDestination(lat, lon) {
  try {
    const d = await apiGet(`/api/school-at?lat=${lat}&lon=${lon}`);
    state.autoDestination = d.school;
    state.destination = d.school; // 새 출발지의 학구 추천으로 리셋 (수동 선택은 이후 다시 가능)
  } catch (e) {
    state.autoDestination = null;
  }
  const p = document.querySelector("#screen-input .dest-name");
  if (p) p.textContent = state.destination || "관악구 학구 밖 — 학교를 직접 선택하세요";
}

// ===== 민원 =====
const MINWON_CATS = {
  "공사": {
    icon: "ti-crane",
    color: "#EF9F27",
    bg: "var(--bg-warning)",
    label: "공사 중 신고",
    subs: ["보도 차단", "도로 공사", "굴착 공사", "비산먼지", "기타 공사"],
  },
  "불량": {
    icon: "ti-tool",
    color: "#E24B4A",
    bg: "var(--bg-danger)",
    label: "시설물 불량",
    subs: ["보도블록 파손", "가로등 불량", "볼라드·펜스 파손", "신호등 불량", "배수구 막힘", "기타"],
  },
  "설치": {
    icon: "ti-circle-plus",
    color: "#1D9E75",
    bg: "var(--bg-success)",
    label: "시설물 설치 요청",
    subs: ["가로등 설치", "볼라드 설치", "횡단보도 설치", "보도 확장", "점자블록", "기타"],
  },
};

const MINWON_KEY = "safe_route_minwon";
function loadMinwon() {
  try { return JSON.parse(localStorage.getItem(MINWON_KEY) || "[]"); } catch (e) { return []; }
}
function saveMinwon(list) {
  try { localStorage.setItem(MINWON_KEY, JSON.stringify(list)); } catch (e) {}
}

async function acquireMinwonLocation() {
  try {
    const pos = await getCurrentPosition();
    state.minwonDraft.location = { lat: pos.lat, lon: pos.lon };
    state.minwonDraft.locationLabel = "현재 위치";
  } catch (e) {
    state.minwonDraft.location = { lat: GWANAK_FALLBACK.lat, lon: GWANAK_FALLBACK.lon };
    state.minwonDraft.locationLabel = "관악구 기준 위치 (GPS 미허용)";
  }
  if (state.currentScreen === "minwon-form") render();
}

// ===== 앱 상태 =====
const state = {
  currentScreen: "home",
  history: ["home"],
  // 입력 단계 상태
  originType: "current", // current | pin | manual
  originLabel: "신림동 1605 인근",
  origin: null, // {lat, lon} — 실제 좌표 (geolocation/지도핀)
  clampedToGwanak: false, // 현재 위치가 관악구 밖이라 기준점으로 고정했는지
  manualQuery: "",
  manualSearching: false,
  manualMessage: "",
  destination: "봉천초등학교", // 현재 선택된 도착 학교 (자동 또는 수동)
  autoDestination: null, // 출발지 학구로 자동 결정된 학교 (드롭다운 추천 상단)
  schools: [], // /api/schools 전체 목록 (드롭다운)
  schoolGates: {}, // {학교명: [{type, lat, lon}]} — 드롭다운 정문/후문 배지용
  destMenuOpen: false,
  remainingMin: 25,
  // 시간 → 자동 모드 매핑
  // 안전 모드 예상시간(14분) 기준으로 잉여 시간 계산
  safestBaselineMin: 14,
  // 프로필
  profileSet: false, // 초기 프로필 설정 완료 여부 (localStorage 연동)
  childName: "서연", // 아이 이름 (호칭·인사에 사용)
  role: "parent", // parent | child — 프로필에서 한 번 고른 역할 (UI 톤만 차이)
  grade: 1,
  style: "safe", // safe | fast (현재 효과)
  baseStyle: "safe", // 페르소나 기본 (nudge reset 기준)
  cap_override: null, // nudge가 명시한 cap (stickiness 유지용)
  // 채팅
  chat: [{ role: "assistant", content: "출발지를 정하면 통학로를 분석할 수 있어요. 현재 위치를 쓰거나 지도에서 출발지를 찍어주세요." }],
  // 백엔드 연동 상태
  route: null, // /api/route 응답 (null이면 DUMMY 사용)
  loading: false,
  error: null,
  usingDummy: false, // 백엔드 실패로 더미 폴백 중인지
  // 전체 지도 화면 상호작용
  mapMode: "route", // "route"(경로 보기) | "risk"(도로 탭해 위험 분석)
  selectedEdge: null, // /api/road/nearest 결과 (risk 모드 탭 시)
  showSchoolZones: true, // 스쿨존 오버레이 표시 여부
  schoolZonesCache: null, // /api/schoolzones 캐시 (한 번만 로드)
  selectedRiskyRoad: null, // 번호 마커 탭 시 선택된 위험 구간 {road, idx}
  preferredGate: null, // 사용자가 선택한 출입문 타입 ("정문" | "후문" | null)
  altRoute: null,      // 비교용 대체 경로 (반대 스타일)
  compareLoading: false,
  // 민원
  minwonList: loadMinwon(),
  minwonDraft: { category: null, subCategory: null, location: null, locationLabel: "", description: "", photoFiles: [], photoUrls: [] },
};

// ===== 내비게이션 GPS 상태 =====
const navState = {
  watchId: null, simTimer: null, simIdx: 0, gpsTimeout: null,
  currentPos: null, segIdx: 0, userMarker: null, arrived: false,
  waypoints: [],
};

// 현재 화면에 쓸 경로 데이터 (백엔드 응답 우선, 없으면 더미)
function currentRoute() {
  return state.route || DUMMY_ROUTE;
}

// 도착 학교의 출입문 요약 (정문/후문 위치·여부). 게이트 정보 없으면 null.
function destGatesSummary(data) {
  const dest = (data && data.destination) || {};
  const gates = Array.isArray(dest.gates) ? dest.gates : [];
  if (!gates.length) return null;
  return {
    name: dest.name,
    gates, // [{type, lat, lon}]
    types: gates.map((g) => g.type),
    arrival: dest.arrival_gate || null, // 경로가 실제 도착한 문
    single: gates.length === 1,
  };
}

// 백엔드 mode → 프론트 배너용 decision (없으면 클라이언트 추정)
function decisionFor(data) {
  if (!data || !data.mode) return decideMode(state.remainingMin, state.safestBaselineMin);
  const m = data.mode;
  return {
    mode: m.mode,
    modeLabel: m.mode_label,
    icon: m.icon,
    bannerClass: m.banner_class,
    explanation: data.time_message || "조건에 맞춰 경로를 안내해요",
    tag: data.warning ? "차선책" : "",
    fallbackHint: data.warning
      ? "지금 조건으로는 충분히 안전한 길이 없어 가능한 선에서 안내해요."
      : undefined,
  };
}

// ===== 시간 → 모드 자동 결정 =====
// 시안에서 합의한 매핑:
//   잉여 +5분 이상: safest (초록 / 정보 배너)
//   -2 ~ +5분:      balanced (노랑 / 경고 배너)
//   -2분 미만:      shortest (빨강 / 위험 배너)
function decideMode(remainingMin, baselineMin) {
  const slack = remainingMin - baselineMin;
  if (slack >= 5) {
    return {
      mode: "safest",
      modeLabel: "안전 우선",
      icon: "ti-shield",
      bannerClass: "banner-info",
      slack,
      explanation: "시간 여유가 충분해서 가장 안전한 길을 골랐어요",
      tag: `${slack}분 여유`,
    };
  }
  if (slack >= -2) {
    return {
      mode: "balanced",
      modeLabel: "균형 잡힌 길",
      icon: "ti-scale",
      bannerClass: "banner-warning",
      slack,
      explanation: "안전과 빠르기를 적절히 섞은 길로 안내해요",
      tag: slack >= 0 ? `${slack}분 여유` : `${Math.abs(slack)}분 부족`,
    };
  }
  return {
    mode: "shortest",
    modeLabel: "빠른 길",
    icon: "ti-bolt",
    bannerClass: "banner-danger",
    slack,
    explanation:
      "시간이 빠듯해서 빠른 길로 안내해요. 그래도 위험도가 가장 높은 구간은 피했어요",
    tag: `${Math.abs(slack)}분 부족`,
    fallbackHint:
      "완전 차단된 위험 도로 때문에 평소보다 100m 돌아갈 수 있어요. 가능하면 출발을 5분 앞당기는 걸 추천해요",
  };
}

// ===== 라우팅 =====
function navigate(screen, opts = {}) {
  if (state.currentScreen === "nav") stopNavigation();
  state.currentScreen = screen;
  if (!opts.replace) state.history.push(screen);
  render();
}

function back() {
  if (state.history.length <= 1) return;
  if (state.currentScreen === "nav") stopNavigation();
  state.history.pop();
  state.currentScreen = state.history[state.history.length - 1];
  render();
}

// ===== 헬퍼 =====
function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[c]);
}

// 마크다운 굵게(**…**)만 <strong> 으로. esc 로 먼저 이스케이프하므로 XSS 안전.
function fmtBold(s) {
  return esc(String(s)).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
}

function formatTime(date) {
  const hours = date.getHours().toString().padStart(2, "0");
  const minutes = date.getMinutes().toString().padStart(2, "0");
  return `${hours}:${minutes}`;
}

function todayLabel() {
  const d = new Date();
  const days = ["일", "월", "화", "수", "목", "금", "토"];
  return `${d.getFullYear()}년 ${d.getMonth() + 1}월 ${d.getDate()}일 ${days[d.getDay()]}요일`;
}

function greetingByHour() {
  const h = new Date().getHours();
  if (h < 11) return "좋은 아침이에요";
  if (h < 17) return "오후예요";
  return "안녕하세요";
}

// 한글 이름의 받침 유무 → 조사 자동 선택 ("서연이의"/"지호의", "서연아"/"지호야")
function hasJongseong(str) {
  if (!str) return false;
  const c = str.charCodeAt(str.length - 1);
  if (c < 0xac00 || c > 0xd7a3) return false; // 한글 음절이 아니면 받침 없음으로 취급
  return (c - 0xac00) % 28 !== 0;
}
function childName() {
  return (state.childName || "").trim() || "우리 아이";
}
function childPossessive() {
  const n = childName();
  return hasJongseong(n) ? `${n}이의` : `${n}의`; // 소유격
}
function childVocative() {
  const n = childName();
  return hasJongseong(n) ? `${n}아` : `${n}야`; // 부름말 (아이 모드)
}

// ===== 내비게이션 GPS 헬퍼 =====

// 더미 경로 폴백 좌표 (API 없을 때 시뮬레이션용)
const ROUTE_COORDS = [
  [37.4841, 126.9295],
  [37.4848, 126.9290],
  [37.4855, 126.9282],
  [37.4861, 126.9270],
  [37.4864, 126.9263],
  [37.4868, 126.9257],
  [37.4871, 126.9254],
  [37.4874, 126.9249],
];

function distanceBetween(a, b) {
  const R = 6371000;
  const dLat = (b[0] - a[0]) * Math.PI / 180;
  const dLon = (b[1] - a[1]) * Math.PI / 180;
  const sinLat = Math.sin(dLat / 2);
  const sinLon = Math.sin(dLon / 2);
  const sq = sinLat * sinLat + Math.cos(a[0] * Math.PI / 180) * Math.cos(b[0] * Math.PI / 180) * sinLon * sinLon;
  return R * 2 * Math.atan2(Math.sqrt(sq), Math.sqrt(1 - sq));
}

function nearestSegIdx(pos, waypoints) {
  let minDist = Infinity, best = navState.segIdx;
  for (let i = navState.segIdx; i < waypoints.length; i++) {
    const d = distanceBetween(pos, waypoints[i]);
    if (d < minDist) { minDist = d; best = i; }
  }
  return { idx: best, dist: minDist };
}

function remainingNavDist(fromPos, waypoints) {
  if (!waypoints.length) return 0;
  let d = distanceBetween(fromPos, waypoints[Math.min(navState.segIdx, waypoints.length - 1)]);
  for (let i = navState.segIdx; i < waypoints.length - 1; i++) {
    d += distanceBetween(waypoints[i], waypoints[i + 1]);
  }
  return Math.max(0, d);
}

function extractWaypoints() {
  const data = state.route;
  if (data && data.geometry) {
    const pts = [];
    data.geometry.forEach((seg) => {
      (seg.coords || []).forEach((c) => {
        if (Array.isArray(c) && c.length === 2) pts.push(c);
      });
    });
    const unique = pts.filter((p, i) => i === 0 || p[0] !== pts[i - 1][0] || p[1] !== pts[i - 1][1]);
    if (unique.length >= 2) return unique;
  }
  return ROUTE_COORDS;
}

function stopNavigation() {
  if (navState.watchId != null) { navigator.geolocation.clearWatch(navState.watchId); navState.watchId = null; }
  if (navState.simTimer) { clearInterval(navState.simTimer); navState.simTimer = null; }
  if (navState.gpsTimeout) { clearTimeout(navState.gpsTimeout); navState.gpsTimeout = null; }
  navState.userMarker = null;
  navState.currentPos = null;
  navState.segIdx = 0;
  navState.arrived = false;
  navState.simIdx = 0;
  navState.waypoints = [];
}

function startNavSimulation(waypoints) {
  if (navState.simTimer) return;
  const pts = [];
  for (let i = 0; i < waypoints.length - 1; i++) {
    for (let s = 0; s < 5; s++) {
      const t = s / 5;
      pts.push([
        waypoints[i][0] + t * (waypoints[i + 1][0] - waypoints[i][0]),
        waypoints[i][1] + t * (waypoints[i + 1][1] - waypoints[i][1]),
      ]);
    }
  }
  pts.push(waypoints[waypoints.length - 1]);
  navState.simIdx = 0;
  navState.simTimer = setInterval(() => {
    if (navState.simIdx >= pts.length) {
      clearInterval(navState.simTimer);
      navState.simTimer = null;
      return;
    }
    const [lat, lon] = pts[navState.simIdx++];
    updateNavPosition(lat, lon);
  }, 600);
}

function updateNavPosition(lat, lon) {
  const waypoints = navState.waypoints;
  if (!waypoints.length) return;
  navState.currentPos = [lat, lon];

  const { idx, dist } = nearestSegIdx([lat, lon], waypoints);
  const offRoute = dist > 80;

  const offEl = document.getElementById("nav-offroute");
  if (offEl) offEl.style.display = offRoute ? "flex" : "none";

  if (!offRoute) navState.segIdx = idx;

  if (navState.userMarker) navState.userMarker.setLatLng([lat, lon]);

  refreshNavInstruction();

  const remDist = remainingNavDist([lat, lon], waypoints);
  const remMin = Math.max(1, Math.round(remDist / 67));
  const eta = new Date(Date.now() + remMin * 60000);

  const distEl = document.getElementById("nav-rem-dist");
  const timeEl = document.getElementById("nav-rem-time");
  const etaEl  = document.getElementById("nav-eta");
  if (distEl) distEl.textContent = remDist > 1000 ? `${(remDist / 1000).toFixed(1)}km` : `${Math.round(remDist)}m`;
  if (timeEl) timeEl.textContent = `${remMin}분`;
  if (etaEl)  etaEl.textContent  = formatTime(eta);

  const dest = waypoints[waypoints.length - 1];
  if (!navState.arrived && distanceBetween([lat, lon], dest) < 20) {
    navState.arrived = true;
    const arrivedEl = document.getElementById("nav-arrived");
    if (arrivedEl) arrivedEl.style.display = "flex";
    clearInterval(navState.simTimer);
    navState.simTimer = null;
  }
}

function refreshNavInstruction() {
  const seg = navState.segIdx;
  const waypoints = navState.waypoints;
  const iconEl = document.getElementById("nav-instr-icon");
  const textEl = document.getElementById("nav-instr-text");
  const distEl = document.getElementById("nav-instr-dist");
  const warnEl = document.getElementById("nav-instr-warn");
  const boxEl  = document.getElementById("nav-dir-icon-box");
  if (!iconEl) return;

  if (seg >= waypoints.length - 1 || navState.arrived) {
    iconEl.className = "ti ti-flag-3";
    if (textEl) textEl.textContent = "목적지 도착";
    if (distEl) distEl.textContent = "";
    if (warnEl) warnEl.style.display = "none";
    if (boxEl)  boxEl.className = "nav-dir-icon";
    return;
  }

  let level = "safe";
  let warn = null;
  const data = state.route;
  if (data && data.geometry) {
    let accumulated = 0;
    for (const geoSeg of data.geometry) {
      const len = (geoSeg.coords || []).length;
      if (seg < accumulated + len) {
        const c = geoSeg.color || "";
        if (c === "#E24B4A" || c === "#E63946") { level = "danger"; warn = "위험 구간입니다. 주의하세요"; }
        else if (c === "#EF9F27" || c === "#F59E0B" || c === "#FFE066" || c === "#FF9933") level = "warn";
        break;
      }
      accumulated += len;
    }
  }

  const distToNext = navState.currentPos
    ? distanceBetween(navState.currentPos, waypoints[Math.min(seg + 1, waypoints.length - 1)])
    : 0;
  const distText = distToNext > 100
    ? `${Math.round(distToNext / 10) * 10}m 후`
    : distToNext > 0 ? `${Math.round(distToNext)}m 후` : "";

  const icons = { safe: "ti-arrow-up", warn: "ti-alert-circle", danger: "ti-alert-triangle" };
  const labels = { safe: "직진", warn: "주의 구간", danger: "위험 구간" };
  iconEl.className = `ti ${icons[level]}`;
  if (textEl) textEl.textContent = labels[level];
  if (distEl) distEl.textContent = distText;
  if (warnEl) { warnEl.textContent = warn || ""; warnEl.style.display = warn ? "block" : "none"; }
  if (boxEl) boxEl.className = level === "danger" ? "nav-dir-icon danger" : level === "warn" ? "nav-dir-icon warn" : "nav-dir-icon";
}

function initNavGPS(map) {
  const waypoints = extractWaypoints();
  navState.waypoints = waypoints;
  navState.segIdx = 0;
  navState.arrived = false;

  navState.userMarker = L.circleMarker(waypoints[0], {
    radius: 11, color: "white", fillColor: "#378ADD", fillOpacity: 1, weight: 3,
  }).addTo(map).bindTooltip("현재 위치");

  map.setView(waypoints[0], 17);

  if (navigator.geolocation) {
    navState.gpsTimeout = setTimeout(() => {
      if (!navState.currentPos) startNavSimulation(waypoints);
    }, 6000);
    navState.watchId = navigator.geolocation.watchPosition(
      (pos) => {
        clearTimeout(navState.gpsTimeout);
        navState.gpsTimeout = null;
        updateNavPosition(pos.coords.latitude, pos.coords.longitude);
      },
      () => {
        clearTimeout(navState.gpsTimeout);
        navState.gpsTimeout = null;
        startNavSimulation(waypoints);
      },
      { enableHighAccuracy: true, timeout: 6000, maximumAge: 0 }
    );
  } else {
    startNavSimulation(waypoints);
  }
}

// ===== Leaflet 지도 =====
const GWANAK_CENTER = [37.4784, 126.9516];
// 현재 위치가 관악구(학구) 밖일 때 GPS를 고정시킬 관악구 내 기준점.
// 관악구 중심부 — 학구 안쪽이라 /api/school-at 가 학교를 돌려주고 경로 계산이 됩니다.
const GWANAK_FALLBACK = { lat: 37.4784, lon: 126.9516 };
const TILE_URL = `https://api.vworld.kr/req/wmts/1.0.0/${VWORLD_KEY}/Base/{z}/{y}/{x}.png`;
let _maps = []; // 활성 Leaflet 인스턴스 (재렌더 시 정리)

function destroyMaps() {
  _maps.forEach((m) => {
    try { m.remove(); } catch (e) {}
  });
  _maps = [];
}

function makeMap(elId, { interactive = true } = {}) {
  const el = document.getElementById(elId);
  if (!el || typeof L === "undefined") return null;
  const map = L.map(el, {
    zoomControl: interactive,
    attributionControl: false,
    dragging: interactive,
    scrollWheelZoom: interactive,
    doubleClickZoom: interactive,
    boxZoom: interactive,
    keyboard: interactive,
    tap: interactive,
    // 줌/페이드 애니메이션 끔: 재렌더로 지도가 제거된 뒤 transitionend가
    // 죽은 지도에서 발화해 _leaflet_pos undefined 크래시를 내던 문제 방지
    zoomAnimation: false,
    fadeAnimation: false,
    markerZoomAnimation: false,
  });
  map.setView(GWANAK_CENTER, 14);
  L.tileLayer(TILE_URL, { maxZoom: 19 }).addTo(map);
  _maps.push(map);
  // innerHTML 직후 컨테이너 크기 확정 전일 수 있어 다음 틱에 재계산.
  // 그 사이 재렌더로 지도가 제거됐을 수 있으니 살아있을 때만.
  setTimeout(() => {
    if (map._container && map._mapPane) {
      try { map.invalidateSize(); } catch (e) {}
    }
  }, 0);
  return map;
}

function originDotMarker(lat, lon) {
  return L.circleMarker([lat, lon], {
    radius: 7, color: "#fff", weight: 2,
    fillColor: "#378ADD", fillOpacity: 1,
  });
}

function schoolIcon() {
  return L.divIcon({
    className: "",
    html:
      '<div style="background:#185fa5;width:28px;height:28px;border-radius:50%;' +
      'display:flex;align-items:center;justify-content:center;' +
      'box-shadow:0 1px 4px rgba(0,0,0,.4);">' +
      '<i class="ti ti-school" style="color:#fff;font-size:16px;"></i></div>',
    iconSize: [28, 28], iconAnchor: [14, 14],
  });
}

function pinIcon() {
  return L.divIcon({
    className: "",
    html:
      '<div style="font-size:34px;line-height:1;transform:translateY(-6px);' +
      'filter:drop-shadow(0 2px 3px rgba(0,0,0,.35));">' +
      '<i class="ti ti-map-pin-filled" style="color:#378ADD;"></i></div>',
    iconSize: [34, 34], iconAnchor: [17, 32],
  });
}

// 현재 위치(GPS)용 핀 — 현재 위치임을 나타내는 표식이 들어간 핀
function currentLocationIcon() {
  return L.divIcon({
    className: "",
    html:
      '<div style="position:relative;width:34px;height:34px;' +
      'filter:drop-shadow(0 2px 3px rgba(0,0,0,.35));">' +
      '<i class="ti ti-map-pin-filled" style="font-size:34px;line-height:1;color:#378ADD;"></i>' +
      '<i class="ti ti-current-location" style="position:absolute;top:6px;left:9px;font-size:15px;color:#fff;"></i>' +
      "</div>",
    iconSize: [34, 34], iconAnchor: [17, 32],
  });
}

// 위험 구간 번호 마커 — 위험 분석 카드의 번호(①②③)와 지도 위 위치를 짝지어 준다.
function riskNumberIcon(n, level) {
  const bg = level === "danger" ? "#E63946" : "#F59E0B";
  return L.divIcon({
    className: "",
    html:
      `<div style="background:${bg};color:#fff;width:24px;height:24px;border-radius:50%;` +
      `display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:700;` +
      `border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.45);">${n}</div>`,
    iconSize: [24, 24], iconAnchor: [12, 12],
  });
}

// 학교 출입문(정문/후문) 마커. 경로가 실제 도착한 문은 학교 핀 + "도착" 강조,
// 나머지 문은 작은 점 + 라벨. 게이트 정보가 없으면 기존 학교 마커로 폴백.
function drawGates(map, dest, all) {
  if (!dest) return;
  const gates = Array.isArray(dest.gates) ? dest.gates : [];
  if (!gates.length) {
    if (dest.lat != null) {
      L.marker([dest.lat, dest.lon], { icon: schoolIcon() }).addTo(map).bindTooltip(dest.name);
      all.push([dest.lat, dest.lon]);
    }
    return;
  }
  gates.forEach((g) => {
    if (g.lat == null || g.lon == null) return;
    const isArrival = dest.arrival_gate && g.type === dest.arrival_gate;
    const label = `${g.type}${isArrival ? " · 도착" : ""}`;
    if (isArrival) {
      L.marker([g.lat, g.lon], { icon: schoolIcon(), zIndexOffset: 1100 })
        .addTo(map)
        .bindTooltip(label, { permanent: true, direction: "top", offset: [0, -16], className: "gate-tooltip arrival" })
        .openTooltip();
    } else {
      L.circleMarker([g.lat, g.lon], {
        radius: 6, color: "#fff", weight: 2, fillColor: "#378ADD", fillOpacity: 0.85,
      })
        .addTo(map)
        .bindTooltip(label, { permanent: true, direction: "top", offset: [0, -8], className: "gate-tooltip" })
        .openTooltip();
    }
    all.push([g.lat, g.lon]);
  });
}

// 백엔드 geometry(위험도별 색 세그먼트) + 출발/도착 마커를 지도에 그림.
// opts.numbered 면 위험 구간마다 번호 마커도 올린다(카드와 매칭).
function crosswalkIcon() {
  return L.divIcon({
    className: "",
    html: '<div class="crosswalk-badge"><i class="ti ti-road" aria-hidden="true"></i>횡단보도</div>',
    iconSize: [64, 20],
    iconAnchor: [32, 10],
  });
}

function drawRoute(map, data, opts = {}) {
  const all = [];
  (data.geometry || []).forEach((seg) => {
    if (!seg.coords || seg.coords.length < 2) return;
    L.polyline(seg.coords, {
      color: seg.color, weight: 6, opacity: 0.9, lineCap: "round", lineJoin: "round",
      interactive: false, // 위험도 보기 모드에서 탭이 폴리라인에 막히지 않도록
    }).addTo(map);
    seg.coords.forEach((c) => all.push(c));
    // 횡단보도 마커
    if (seg.is_crosswalk && seg.crosswalk_mid) {
      L.marker(seg.crosswalk_mid, { icon: crosswalkIcon(), interactive: false, zIndexOffset: 500 }).addTo(map);
    }
  });
  const o = data.origin && data.origin.snapped;
  if (o) {
    originDotMarker(o.lat, o.lon).addTo(map).bindTooltip("출발");
    all.push([o.lat, o.lon]);
  }
  drawGates(map, data.destination, all);
  if (opts.numbered && Array.isArray(data.risky_roads)) {
    data.risky_roads.forEach((r, i) => {
      if (!r.coord || r.coord.length !== 2) return;
      const marker = L.marker([r.coord[0], r.coord[1]], { icon: riskNumberIcon(i + 1, r.level), zIndexOffset: 1000 })
        .addTo(map);
      marker.on("click", (ev) => {
        L.DomEvent.stopPropagation(ev);
        state.selectedRiskyRoad = { road: r, idx: i };
        state.selectedEdge = null;
        updateRiskSheet();
      });
      all.push([r.coord[0], r.coord[1]]);
    });
  }
  if (all.length >= 2) map.fitBounds(L.latLngBounds(all), { padding: [34, 34] });
  else if (all.length === 1) map.setView(all[0], 16);
}

// 현재 화면에 필요한 Leaflet 지도를 마운트 (render() 끝에서 호출)
function mountMaps() {
  const data = state.route;
  if (state.currentScreen === "map" && data && data.geometry) {
    const m = makeMap("leaflet-full", { interactive: true });
    if (m) {
      drawRoute(m, data, { numbered: true });
      m.on("click", (e) => onMapTap(m, e.latlng));
      if (state.showSchoolZones) drawSchoolZones(m);
    }
  } else if (state.currentScreen === "nav") {
    if (data && data.geometry) {
      const m = makeMap("leaflet-nav", { interactive: true });
      if (m) {
        drawRoute(m, data, { numbered: false });
        if (state.showSchoolZones) drawSchoolZones(m);
        initNavGPS(m);
      }
    } else {
      // 더미 데이터 모드: 지도 없이 시뮬레이션만
      navState.waypoints = ROUTE_COORDS;
      navState.segIdx = 0;
      navState.arrived = false;
      setTimeout(() => startNavSimulation(ROUTE_COORDS), 2000);
    }
  } else if (state.currentScreen === "result" && data && data.geometry) {
    const m = makeMap("leaflet-preview", { interactive: false });
    if (m) drawRoute(m, data, { numbered: true });
  } else if (state.currentScreen === "compare") {
    if (state.route?.geometry) {
      const m1 = makeMap("leaflet-compare-current", { interactive: false });
      if (m1) drawRoute(m1, state.route, { numbered: false });
    }
    if (state.altRoute?.geometry) {
      const m2 = makeMap("leaflet-compare-alt", { interactive: false });
      if (m2) drawRoute(m2, state.altRoute, { numbered: false });
    }
  } else if (state.currentScreen === "minwon-form" && state.minwonDraft.location) {
    const { lat, lon } = state.minwonDraft.location;
    const m = makeMap("leaflet-minwon", { interactive: true });
    if (m) {
      m.setView([lat, lon], 17);
      const mk = L.marker([lat, lon], { icon: pinIcon(), draggable: true }).addTo(m);
      const updatePos = (latlng) => {
        state.minwonDraft.location = { lat: latlng.lat, lon: latlng.lng };
        state.minwonDraft.locationLabel = `위도 ${latlng.lat.toFixed(5)}, 경도 ${latlng.lng.toFixed(5)}`;
        const lbl = document.getElementById("minwon-loc-label");
        if (lbl) lbl.textContent = state.minwonDraft.locationLabel;
      };
      mk.on("dragend", (e) => updatePos(e.target.getLatLng()));
      m.on("click", (e) => { mk.setLatLng(e.latlng); updatePos(e.latlng); });
    }
  } else if (state.currentScreen === "input" && (state.originType === "pin" || state.originType === "manual")) {
    mountPinPicker();
  } else if (state.currentScreen === "input" && state.origin) {
    const m = makeMap("leaflet-mini", { interactive: false });
    if (m) {
      L.marker([state.origin.lat, state.origin.lon], { icon: currentLocationIcon() })
        .addTo(m)
        .bindTooltip("현재 위치");
      m.setView([state.origin.lat, state.origin.lon], 16);
    }
  }
}

// ── 핀 모드: 지도 탭으로 출발지 지정 ──
let _pinMarker = null;
// 선택 위치 마커를 만들고 "선택한 출발지" 라벨(영구 툴팁)을 붙인다.
function addPinMarker(map, latlng) {
  return L.marker(latlng, { icon: pinIcon() })
    .addTo(map)
    .bindTooltip("선택한 출발지", { permanent: true, direction: "top", offset: [0, -30], className: "pin-tooltip" })
    .openTooltip();
}
function mountPinPicker() {
  const m = makeMap("leaflet-pin", { interactive: true });
  if (!m) return;
  _pinMarker = null;
  if (state.origin) {
    _pinMarker = addPinMarker(m, [state.origin.lat, state.origin.lon]);
    m.setView([state.origin.lat, state.origin.lon], 16);
  }
  m.on("click", (e) => {
    const { lat, lng } = e.latlng;
    state.origin = { lat, lon: lng };
    state.originLabel = state.originType === "manual" ? "검색 위치에서 핀 조정" : "지도에서 선택한 위치";
    if (state.originType === "manual") state.manualMessage = "핀 위치를 조정했어요. 이 위치를 출발지로 사용할게요.";
    state.clampedToGwanak = false; // 직접 지정한 출발지이므로 고정 안내 해제
    state.route = null; // 출발지 바뀌면 기존 경로 무효화
    if (_pinMarker) _pinMarker.setLatLng(e.latlng);
    else _pinMarker = addPinMarker(m, e.latlng);
    // 라벨/버튼만 갱신 (지도 줌·중심 유지 위해 전체 재렌더 안 함)
    const disp = document.querySelector("#screen-input .location-display p");
    if (disp) disp.textContent = state.originLabel;
    const chk = document.querySelector("#screen-input .location-display .check");
    if (chk) chk.style.visibility = "visible";
    resolveDestination(lat, lng); // 학구 추천 도착지 실시간 갱신 (DOM만)
  });
}

// ── 위험도 보기 모드: 전체 지도 탭 → 최근접 도로 분석 ──
const BAND_COLOR = { "안전": "#1D9E75", "주의": "#FFE066", "위험": "#FF9933", "매우 위험": "#E63946" };
let _riskHighlight = null;

async function drawSchoolZones(map) {
  try {
    if (!state.schoolZonesCache) {
      state.schoolZonesCache = await apiGet("/api/schoolzones");
    }
    if (!map._container || !map._mapPane) return; // map이 이미 destroy됐으면 무시
    L.geoJSON(state.schoolZonesCache, {
      style: { color: "#378ADD", weight: 1.5, fillColor: "#E6F1FB", fillOpacity: 0.18, opacity: 0.8 },
      onEachFeature(feature, layer) {
        if (feature.properties?.school_name) {
          layer.bindTooltip(feature.properties.school_name, { sticky: true });
        }
      },
    }).addTo(map);
  } catch (e) {
    // 백엔드 없거나 실패 → 조용히 무시
  }
}

async function onMapTap(map, latlng) {
  if (state.mapMode !== "risk") return;
  state.selectedRiskyRoad = null;
  state.selectedEdge = { loading: true };
  updateRiskSheet();
  try {
    const d = await apiPost("/api/road/nearest", { lat: latlng.lat, lon: latlng.lng });
    state.selectedEdge = d;
    if (_riskHighlight) { try { map.removeLayer(_riskHighlight); } catch (e) {} }
    if (d.geom && d.geom.length >= 2) {
      const color = (d.facts && BAND_COLOR[d.facts.band]) || "#111";
      _riskHighlight = L.polyline(d.geom, { color, weight: 9, opacity: 0.95, lineCap: "round", interactive: false }).addTo(map);
    }
  } catch (e) {
    state.selectedEdge = { error: e.message };
  }
  updateRiskSheet();
}

// 바텀시트만 직접 갱신 (지도 줌·중심 유지 위해 전체 재렌더 안 함)
function updateRiskSheet() {
  const sheet = document.getElementById("map-sheet");
  if (!sheet) return;
  sheet.innerHTML = `<div class="sheet-handle"></div>` + riskSheetHtml();
}

// 도착지 드롭다운: 학구 추천(상단) + 전체 학교 목록
function renderDestMenu() {
  const auto = state.autoDestination;
  const gateBadge = (name) => {
    const types = (state.schoolGates[name] || []).map((g) => g.type);
    if (!types.length) return "";
    return `<span class="dest-gate-badge"><i class="ti ti-door" aria-hidden="true"></i>${esc(types.join("·"))}</span>`;
  };
  const item = (name, isAuto) => `
    <button class="dest-item${name === state.destination ? " active" : ""}" data-school="${esc(name)}">
      <i class="ti ti-school" aria-hidden="true"></i>
      <span class="dest-item-name">${esc(name)}</span>
      ${gateBadge(name)}
      ${isAuto ? `<span class="dest-auto-badge">학구 추천</span>` : ""}
      ${name === state.destination ? `<i class="ti ti-check dest-item-check" aria-hidden="true"></i>` : ""}
    </button>`;
  const others = state.schools.filter((s) => s !== auto);
  const list = [
    auto
      ? item(auto, true)
      : `<p class="dest-menu-empty">출발지를 먼저 지정하면 학구 추천이 떠요. 아래에서 직접 골라도 됩니다.</p>`,
    ...others.map((n) => item(n, false)),
  ].join("");
  return `<div class="dest-menu">${list || `<p class="dest-menu-empty">학교 목록을 불러오지 못했어요 (백엔드 확인).</p>`}</div>`;
}

// ===== 화면들 =====

function renderProfile() {
  const onboarding = !state.profileSet;
  const lockSafe = state.grade <= 3;
  return `
    <div class="screen active" id="screen-profile">
      <header class="header">
        ${onboarding ? "" : `<button class="back" data-action="back" aria-label="뒤로"><i class="ti ti-arrow-left" aria-hidden="true"></i></button>`}
        <div class="header-title">
          <h1>${onboarding ? "프로필 설정" : "프로필"}</h1>
          <p class="subtitle">아이 정보를 알려주시면 맞춤 경로를 추천해요</p>
        </div>
      </header>

      <div class="scroll-area" style="padding: 16px;">
        <p class="input-label">누가 사용하나요?</p>
        <div class="style-options">
          <button class="style-option${state.role === "parent" ? " active" : ""}" data-role="parent">
            <i class="ti ti-user-heart" aria-hidden="true"></i>
            <div><p class="so-title">부모</p><p class="so-desc">아이의 통학로를 계획·확인해요</p></div>
          </button>
          <button class="style-option${state.role === "child" ? " active" : ""}" data-role="child">
            <i class="ti ti-mood-kid" aria-hidden="true"></i>
            <div><p class="so-title">아이</p><p class="so-desc">안내를 따라 직접 등교해요</p></div>
          </button>
        </div>

        <p class="input-label" style="margin-top: 20px;">${state.role === "child" ? "이름" : "아이 이름"}</p>
        <input type="text" id="child-name" class="text-input" maxlength="10"
          placeholder="예: 서연" value="${esc(state.childName)}"
          aria-label="이름" autocomplete="off" />

        <p class="input-label" style="margin-top: 20px;">아이 학년</p>
        <div class="grade-grid">
          ${[1, 2, 3, 4, 5, 6]
            .map((g) => `<button class="grade-btn${state.grade === g ? " active" : ""}" data-grade="${g}">${g}학년</button>`)
            .join("")}
        </div>

        <p class="input-label" style="margin-top: 20px;">통학 스타일</p>
        ${
          lockSafe
            ? `<p class="hint-text" style="margin: 0 0 8px; font-size: 12px; color: var(--text-secondary);">
                 <i class="ti ti-shield" aria-hidden="true"></i> 1~3학년은 안전을 위해 안전형으로 안내해요
               </p>`
            : ""
        }
        <div class="style-options">
          <button class="style-option${state.style === "safe" ? " active" : ""}" data-style="safe">
            <i class="ti ti-shield" aria-hidden="true"></i>
            <div><p class="so-title">안전형</p><p class="so-desc">위험한 도로를 최대한 피해요</p></div>
          </button>
          <button class="style-option${state.style === "fast" ? " active" : ""}${lockSafe ? " disabled" : ""}"
            data-style="fast" ${lockSafe ? "disabled" : ""}>
            <i class="ti ti-bolt" aria-hidden="true"></i>
            <div><p class="so-title">효율형</p><p class="so-desc">빠른 길 위주 (위험 도로는 회피)</p></div>
          </button>
        </div>
      </div>

      <div class="action-bar">
        <button class="btn btn-primary btn-block" data-action="save-profile">
          ${onboarding ? "시작하기" : "저장"}
        </button>
      </div>
    </div>
  `;
}

function renderHome() {
  return `
    <div class="screen active" id="screen-home">
      <div class="home-header">
        <div class="home-greeting">
          <p class="date">${esc(todayLabel())} · ${state.role === "child" ? "아이 모드" : "부모 모드"}</p>
          <h1>${state.role === "child" ? esc(`${childName()}, ${greetingByHour()}`) : esc(greetingByHour())}</h1>
        </div>
        <button class="avatar" data-action="profile" aria-label="프로필">
          <i class="ti ti-user" aria-hidden="true"></i>
        </button>
      </div>

      <div class="hero-card">
        <div class="hero-header">
          <i class="ti ti-sun" aria-hidden="true"></i>
          <span>오늘 등교</span>
        </div>
        <p class="hero-body">${
          state.role === "child"
            ? esc(`${childVocative()}, 오늘도 안전하게 학교 가자!`)
            : esc(`${childPossessive()} 등교 시간이에요`)
        }</p>
        <button class="hero-btn" data-action="quick-route">
          <i class="ti ti-route" aria-hidden="true"></i>${state.role === "child" ? "길 안내 받기" : "경로 찾기"}
        </button>
      </div>

      <div class="scroll-area">
        <p class="section-title">자주 가는 경로</p>
        ${SAVED_ROUTES.map(
          (r) => `
          <button class="route-item" data-action="open-route">
            <div class="route-icon"><i class="ti ${r.icon}" aria-hidden="true"></i></div>
            <div class="route-info">
              <p class="name">${esc(r.name)}</p>
              <p class="meta">${esc(r.meta)}</p>
            </div>
            <div class="route-arrow"><i class="ti ti-chevron-right" aria-hidden="true"></i></div>
          </button>
        `
        ).join("")}

        <p class="section-title">새로 찾기</p>
        <button class="add-route-btn" data-action="new-route">
          <i class="ti ti-plus" aria-hidden="true"></i>다른 경로 검색
        </button>
        <div style="height: 16px;"></div>
      </div>

      <nav class="bottom-nav">
        <button class="active" aria-label="홈">
          <i class="ti ti-home" aria-hidden="true"></i><span>홈</span>
        </button>
        <button data-action="chat" aria-label="대화">
          <i class="ti ti-message" aria-hidden="true"></i><span>대화</span>
        </button>
        <button data-action="minwon" aria-label="민원">
          <i class="ti ti-speakerphone" aria-hidden="true"></i><span>민원</span>
        </button>
        <button aria-label="설정">
          <i class="ti ti-settings" aria-hidden="true"></i><span>설정</span>
        </button>
      </nav>
    </div>
  `;
}

function renderInput() {
  const decision = decideMode(state.remainingMin, state.safestBaselineMin);
  const arrivalTime = new Date(Date.now() + state.remainingMin * 60000);

  return `
    <div class="screen active" id="screen-input">
      <header class="header">
        <button class="back" data-action="back" aria-label="뒤로">
          <i class="ti ti-arrow-left" aria-hidden="true"></i>
        </button>
        <div class="header-title">
          <h1>출발지 · 시간</h1>
        </div>
      </header>

      <div class="scroll-area">
        <div class="input-section">
          <p class="input-label">출발지</p>
          <div class="segment" role="tablist">
            <button class="${state.originType === "current" ? "active" : ""}" data-origin-type="current">
              <i class="ti ti-current-location" aria-hidden="true"></i>현재 위치
            </button>
            <button class="${state.originType === "pin" ? "active" : ""}" data-origin-type="pin">
              <i class="ti ti-map-pin" aria-hidden="true"></i>지도에서
            </button>
            <button class="${state.originType === "manual" ? "active" : ""}" data-origin-type="manual">
              <i class="ti ti-keyboard" aria-hidden="true"></i>입력
            </button>
          </div>

          ${
            state.originType === "manual"
              ? `<div class="manual-origin-box">
                   <label class="manual-origin-label" for="manual-origin-input">아파트·주소 검색</label>
                   <div class="manual-origin-row">
                     <input id="manual-origin-input" class="manual-origin-input" value="${esc(state.manualQuery)}"
                            placeholder="예: 관악드림타운 101동, 봉천동 1712" autocomplete="off" />
                     <button class="manual-origin-btn" data-action="geocode-origin" ${state.manualSearching ? "disabled" : ""}>
                       <i class="ti ${state.manualSearching ? "ti-loader-2 ti-spin" : "ti-search"}" aria-hidden="true"></i>
                     </button>
                   </div>
                   <p class="manual-origin-help">${esc(state.manualMessage || "동까지 검색되지 않으면 아파트 단지 위치를 먼저 잡고, 지도에서 핀을 살짝 옮겨주세요.")}</p>
                 </div>`
              : ""
          }

          ${
            state.originType === "pin" || state.originType === "manual"
              ? `<div style="position: relative; height: 280px; background: var(--bg-tertiary); border-radius: var(--radius-md); overflow: hidden; margin-top: 10px;">
                   <div id="leaflet-pin" style="position:absolute;inset:0;z-index:0;"></div>
                 </div>
                 <p class="hint-text" style="margin:6px 2px 0;font-size:12px;color:var(--text-secondary);">
                   <i class="ti ti-hand-finger" aria-hidden="true"></i> ${state.originType === "manual" ? "검색된 위치가 조금 다르면 지도를 탭해 핀을 옮기세요" : "지도를 탭해 출발지를 지정하세요"}
                 </p>`
              : `<div style="position: relative; height: 160px; background: var(--bg-tertiary); border-radius: var(--radius-md); overflow: hidden; margin-top: 10px;">
                   ${
                     state.origin
                       ? `<div id="leaflet-mini" style="position:absolute;inset:0;z-index:0;"></div>`
                       : `${renderMiniMap()}
                          <div style="position: absolute; top: 50%; left: 50%; transform: translate(-50%, -100%); pointer-events: none;">
                            <i class="ti ti-map-pin-filled" style="font-size: 32px; color: var(--text-info);" aria-hidden="true"></i>
                          </div>`
                   }
                 </div>`
          }

          <div class="location-display">
            <i class="ti ti-map-pin location" aria-hidden="true"></i>
            <p>${esc(state.originLabel)}</p>
            <i class="ti ti-check check" aria-hidden="true"></i>
          </div>
        </div>

        <div class="input-section">
          <p class="input-label">도착지</p>
          <button class="dest-select" data-action="toggle-dest-menu" aria-expanded="${state.destMenuOpen}">
            <i class="ti ti-school" aria-hidden="true"></i>
            <p class="dest-name">${esc(state.destination || "출발지를 지정하면 학구로 자동 결정돼요")}</p>
            <i class="ti ti-chevron-${state.destMenuOpen ? "up" : "down"}" aria-hidden="true"></i>
          </button>
          ${state.destMenuOpen ? renderDestMenu() : ""}
        </div>

        <div class="input-section">
          <div class="time-display">
            <p class="label">도착까지 남은 시간</p>
            <p class="value"><span id="time-value">${state.remainingMin}</span>분<span class="arrival">${formatTime(arrivalTime)} 도착 기준</span></p>
          </div>
          <input type="range" id="time-slider" min="1" max="40" step="1" value="${state.remainingMin}" aria-label="남은 시간 (분)" />
          <div class="slider-ticks">
            <span>1분</span><span>20분</span><span>40분</span>
          </div>

          <div class="banner ${decision.bannerClass}" id="mode-preview" style="margin-top: 14px;">
            <div class="banner-header">
              <i class="ti ${decision.icon}" aria-hidden="true"></i>
              <span>${esc(decision.modeLabel)} 모드</span>
            </div>
            <p class="banner-body">${esc(decision.explanation)}</p>
          </div>
        </div>

        <div style="height: 16px;"></div>
      </div>

      <div class="action-bar">
        <button class="btn btn-primary btn-block" data-action="find-route">
          경로 찾기
        </button>
      </div>
    </div>
  `;
}

function renderMiniMap() {
  return `
    <svg viewBox="0 0 308 160" style="width: 100%; height: 100%;" aria-hidden="true">
      <rect width="308" height="160" fill="#F1EFE8" opacity="0.5"/>
      <line x1="0" y1="40" x2="308" y2="40" stroke="#D3D1C7" stroke-width="0.5"/>
      <line x1="0" y1="80" x2="308" y2="80" stroke="#D3D1C7" stroke-width="0.5"/>
      <line x1="0" y1="120" x2="308" y2="120" stroke="#D3D1C7" stroke-width="0.5"/>
      <line x1="80" y1="0" x2="80" y2="160" stroke="#D3D1C7" stroke-width="0.5"/>
      <line x1="160" y1="0" x2="160" y2="160" stroke="#D3D1C7" stroke-width="0.5"/>
      <line x1="240" y1="0" x2="240" y2="160" stroke="#D3D1C7" stroke-width="0.5"/>
      <path d="M 0 70 Q 60 65 80 60 T 160 50 T 240 55 T 308 50" stroke="#B4B2A9" stroke-width="2" fill="none"/>
      <path d="M 0 110 Q 80 105 160 100 T 308 95" stroke="#B4B2A9" stroke-width="1.5" fill="none"/>
      <path d="M 160 0 L 160 160" stroke="#B4B2A9" stroke-width="1.5" fill="none" opacity="0.4"/>
      <circle cx="154" cy="76" r="14" fill="#378ADD" opacity="0.15"/>
      <circle cx="154" cy="76" r="6" fill="#378ADD" stroke="white" stroke-width="2"/>
    </svg>
  `;
}

function renderRoutePreviewSvg() {
  return `
    <svg viewBox="0 0 308 130" style="width: 100%; height: 100%;" aria-hidden="true">
      <path d="M 30 95 L 80 85 L 110 65 L 160 60 L 200 35 L 250 30" stroke="#1D9E75" stroke-width="4" fill="none" stroke-linecap="round"/>
      <path d="M 200 35 L 230 45" stroke="#EF9F27" stroke-width="4" fill="none" stroke-linecap="round"/>
      <circle cx="30" cy="95" r="6" fill="#378ADD" stroke="white" stroke-width="2"/>
      <circle cx="250" cy="30" r="6" fill="#185fa5" stroke="white" stroke-width="2"/>
    </svg>
  `;
}

function renderRouteFullSvg() {
  return `
    <svg viewBox="0 0 340 380" style="width: 100%; height: 100%; position: absolute; inset: 0;" aria-hidden="true">
      <rect width="340" height="380" fill="transparent"/>
      <line x1="0" y1="80" x2="340" y2="80" stroke="#D3D1C7" stroke-width="1" opacity="0.6"/>
      <line x1="0" y1="160" x2="340" y2="160" stroke="#D3D1C7" stroke-width="1" opacity="0.6"/>
      <line x1="0" y1="240" x2="340" y2="240" stroke="#D3D1C7" stroke-width="1" opacity="0.6"/>
      <line x1="0" y1="320" x2="340" y2="320" stroke="#D3D1C7" stroke-width="1" opacity="0.6"/>
      <line x1="80" y1="0" x2="80" y2="380" stroke="#D3D1C7" stroke-width="1" opacity="0.6"/>
      <line x1="170" y1="0" x2="170" y2="380" stroke="#D3D1C7" stroke-width="1" opacity="0.6"/>
      <line x1="260" y1="0" x2="260" y2="380" stroke="#D3D1C7" stroke-width="1" opacity="0.6"/>

      <path d="M 50 300 L 90 280 L 120 230" stroke="#1D9E75" stroke-width="5" fill="none" stroke-linecap="round"/>
      <path d="M 120 230 L 170 200 L 200 170" stroke="#1D9E75" stroke-width="5" fill="none" stroke-linecap="round"/>
      <path d="M 200 170 L 240 150" stroke="#EF9F27" stroke-width="5" fill="none" stroke-linecap="round"/>
      <path d="M 240 150 L 270 140 L 290 110" stroke="#1D9E75" stroke-width="5" fill="none" stroke-linecap="round"/>

      <circle cx="50" cy="300" r="9" fill="#378ADD" stroke="white" stroke-width="2.5"/>
      <circle cx="290" cy="110" r="9" fill="#185fa5" stroke="white" stroke-width="2.5"/>

      <g>
        <circle cx="220" cy="160" r="13" fill="#EF9F27" stroke="white" stroke-width="2"/>
        <text x="220" y="165" font-size="13" fill="white" text-anchor="middle" font-weight="600">!</text>
      </g>

      <rect x="42" y="312" width="46" height="16" rx="3" fill="white" stroke="#0C447C" stroke-width="0.5"/>
      <text x="65" y="323" font-size="9" fill="#0C447C" text-anchor="middle" font-weight="500">신림역</text>

      <rect x="265" y="86" width="50" height="16" rx="3" fill="white" stroke="#0c447c" stroke-width="0.5"/>
      <text x="290" y="97" font-size="9" fill="#0c447c" text-anchor="middle" font-weight="500">봉천초</text>
    </svg>
  `;
}

// 경로 생성 실패(서버 정상 + 422 등) 안내 화면
function renderRouteError() {
  return `
    <div class="screen active" id="screen-result">
      <header class="header">
        <button class="back" data-action="back" aria-label="뒤로"><i class="ti ti-arrow-left" aria-hidden="true"></i></button>
        <div class="header-title"><h1>경로를 만들지 못했어요</h1></div>
      </header>
      <div class="scroll-area" style="padding: 16px;">
        <div class="banner banner-warning" style="margin-bottom: 14px;">
          <div class="banner-header"><i class="ti ti-alert-triangle" aria-hidden="true"></i><span>안내</span></div>
          <p class="banner-body">${esc(state.error || "조건에 맞는 경로를 계산하지 못했어요.")}</p>
        </div>
        <button class="btn btn-primary btn-block" data-action="fix-origin">
          <i class="ti ti-map-pin" aria-hidden="true"></i>지도에서 출발지 다시 선택
        </button>
        <button class="btn btn-block" style="margin-top: 10px;" data-action="back">
          <i class="ti ti-arrow-left" aria-hidden="true"></i>돌아가기
        </button>
      </div>
    </div>
  `;
}

// 결과 화면의 "출입문" 카드 — 정문/후문 버튼으로 선택 변경 가능.
function renderGateCard(g) {
  const chips = g.gates
    .map((gate) => {
      const active = state.preferredGate ? gate.type === state.preferredGate : gate.type === g.arrival;
      return `<button class="gate-chip${active ? " active" : ""}" data-action="select-gate" data-gate-type="${esc(gate.type)}">
        <i class="ti ${active ? "ti-door-enter" : "ti-door"}" aria-hidden="true"></i>${esc(gate.type)}
        ${active ? `<i class="ti ti-check" style="font-size:11px;margin-left:2px;" aria-hidden="true"></i>` : ""}
      </button>`;
    })
    .join("");
  const note = g.single
    ? `이 학교는 <strong>${esc(g.types[0])}</strong>만 등록돼 있어요.`
    : `출입문을 선택하면 해당 문으로 경로를 다시 계산해요.`;
  return `
    <div class="gate-card">
      <div class="gate-card-head">
        <i class="ti ti-door-enter" aria-hidden="true"></i>
        <span>${esc(g.name || "학교")} 출입문</span>
      </div>
      <div class="gate-chips">${chips}</div>
      <p class="gate-card-note">${note}</p>
      <button class="btn btn-block gate-map-btn" data-action="open-map">
        <i class="ti ti-map-pin" aria-hidden="true"></i>지도에서 위치 보기
      </button>
    </div>`;
}

function renderResult() {
  if (state.loading) {
    return `
    <div class="screen active" id="screen-result">
      <header class="header">
        <button class="back" data-action="back" aria-label="뒤로"><i class="ti ti-arrow-left" aria-hidden="true"></i></button>
        <div class="header-title"><h1>경로 찾는 중…</h1></div>
      </header>
      <div class="scroll-area" style="display:flex;flex-direction:column;align-items:center;justify-content:center;gap:14px;padding-top:80px;">
        <i class="ti ti-loader-2 ti-spin" style="font-size:40px;color:var(--text-info);" aria-hidden="true"></i>
        <p style="color:var(--text-secondary);font-size:14px;">안전한 길을 계산하고 있어요</p>
      </div>
    </div>`;
  }

  // 서버는 정상인데 경로를 못 만든 경우(422 등): 더미 대신 실제 안내 + 수정 동선 제공
  if (!state.route && state.error && !state.usingDummy) {
    return renderRouteError();
  }

  const data = currentRoute();
  const decision = state.route ? decisionFor(data) : decideMode(state.remainingMin, state.safestBaselineMin);
  const { segments, distance_m, duration_min, school_zone_ratio, risky_roads } = data;
  const riskyCount = risky_roads.length;
  const hasDanger = risky_roads.some((r) => r.level === "danger");
  const riskClass = hasDanger ? "danger" : "warn";
  const firstRisky = risky_roads[0];
  const gateSum = destGatesSummary(data);

  return `
    <div class="screen active" id="screen-result">
      <header class="header">
        <button class="back" data-action="back" aria-label="뒤로">
          <i class="ti ti-arrow-left" aria-hidden="true"></i>
        </button>
        <div class="header-title">
          <h1>${esc(state.originLabel)} → ${esc(state.destination)}</h1>
          <p class="subtitle">${state.remainingMin}분 안에 도착 · ${esc(childName())} ${state.grade}학년</p>
        </div>
      </header>

      <div class="scroll-area">
        <div class="result-body">
          ${
            state.usingDummy
              ? `<div class="banner banner-warning" style="margin-bottom: 12px;">
                   <div class="banner-header"><i class="ti ti-wifi-off" aria-hidden="true"></i><span>예시 경로 표시 중</span></div>
                   <p class="banner-body">서버에 연결하지 못해 예시 데이터를 보여드려요. 실제 경로를 보려면 잠시 후 다시 시도해주세요.</p>
                 </div>`
              : ""
          }
          ${
            state.clampedToGwanak
              ? `<div class="banner banner-info" style="margin-bottom: 12px;">
                   <div class="banner-header"><i class="ti ti-map-pin-cog" aria-hidden="true"></i><span>관악구 기준 위치로 안내</span></div>
                   <p class="banner-body">현재 위치가 관악구 밖이라, 관악구 안의 기준점을 출발지로 사용했어요. ‘지도에서’ 탭으로 실제 출발지를 직접 지정할 수 있어요.</p>
                 </div>`
              : ""
          }
          ${
            !state.usingDummy
              ? `<div class="banner ${decision.bannerClass}" style="margin-bottom: 12px;">
                   <div class="banner-header">
                     <i class="ti ${decision.icon}" aria-hidden="true"></i>
                     <span>${esc(decision.modeLabel)} 추천</span>
                     ${decision.tag ? `<span class="banner-tag">${esc(decision.tag)}</span>` : ""}
                   </div>
                   <p class="banner-body">${esc(decision.explanation)}</p>
                 </div>`
              : ""
          }

          ${
            decision.fallbackHint
              ? `
            <div class="banner banner-warning" style="margin-bottom: 12px;">
              <div class="banner-header">
                <i class="ti ti-info-circle" aria-hidden="true"></i>
                <span>차선책 안내 중</span>
              </div>
              <p class="banner-body">${esc(decision.fallbackHint)}</p>
            </div>
          `
              : ""
          }

          <div class="map-preview">
            ${
              state.route && state.route.geometry
                ? `<div id="leaflet-preview" style="position:absolute;inset:0;z-index:0;"></div>`
                : renderRoutePreviewSvg()
            }
            <button class="map-expand-btn" data-action="open-map">
              <i class="ti ti-arrows-maximize" aria-hidden="true"></i>지도 열기
            </button>
          </div>

          <div class="metric-grid">
            <div class="metric">
              <p class="metric-label">거리</p>
              <p class="metric-value">${distance_m}<span class="unit">m</span></p>
            </div>
            <div class="metric">
              <p class="metric-label">예상</p>
              <p class="metric-value">${duration_min}<span class="unit">분</span></p>
            </div>
            <div class="metric">
              <p class="metric-label">스쿨존</p>
              <p class="metric-value">${Math.round(school_zone_ratio * 100)}<span class="unit">%</span></p>
            </div>
          </div>

          ${gateSum ? renderGateCard(gateSum) : ""}

          ${
            firstRisky
              ? `<button class="risk-summary ${riskClass}" data-action="open-map">
                   <i class="ti ti-alert-triangle head" aria-hidden="true"></i>
                   <div class="risk-summary-text">
                     <p class="title">${hasDanger ? "위험" : "주의"} 구간 ${riskyCount}곳</p>
                     <p class="sub">지도에서 번호를 탭해 위험 이유 확인</p>
                   </div>
                   <i class="ti ti-chevron-right chev" aria-hidden="true"></i>
                 </button>`
              : `<button class="risk-summary safe" data-action="open-map">
                   <i class="ti ti-shield-check head" aria-hidden="true"></i>
                   <div class="risk-summary-text">
                     <p class="title">조심할 구간 없음</p>
                     <p class="sub">이 경로엔 특별히 위험한 도로가 없어요</p>
                   </div>
                   <i class="ti ti-chevron-right chev" aria-hidden="true"></i>
                 </button>`
          }

          <button class="btn btn-dashed btn-block" style="margin-top: 10px;"
            ${state.usingDummy ? "disabled style=\"opacity:0.4;cursor:not-allowed;\"" : "data-action=\"compare-routes\""}
            aria-label="다른 경로 비교">
            <i class="ti ti-route" aria-hidden="true"></i>다른 경로 비교
          </button>
        </div>
      </div>

      <div class="action-bar">
        ${
          state.usingDummy
            ? `<button class="btn" style="flex:1;opacity:0.4;cursor:not-allowed;" disabled title="서버 연결 후 사용 가능">
                 <i class="ti ti-message" aria-hidden="true"></i>길 조건 바꾸기
               </button>`
            : `<button class="btn" style="flex:1;" data-action="chat">
                 <i class="ti ti-message" aria-hidden="true"></i>길 조건 바꾸기
               </button>`
        }
        <button class="btn btn-primary" style="flex: 1.4;" data-action="start-nav">
          <i class="ti ti-navigation" aria-hidden="true"></i>안내 시작
        </button>
      </div>
    </div>
  `;
}

function renderRiskDetail() {
  const { segments, risky_roads } = currentRoute();
  const total = segments.total;
  const safe_m = segments.safe_m ?? segments.safe;
  const warn_m = segments.warn_m ?? segments.warn;
  const danger_m = segments.danger_m ?? segments.danger;
  const total_m = segments.total_m ?? segments.total;
  const pct = (m) => Math.round((m / total_m) * 100);

  return `
    <div class="screen active" id="screen-risk">
      <header class="header">
        <button class="back" data-action="back" aria-label="뒤로">
          <i class="ti ti-arrow-left" aria-hidden="true"></i>
        </button>
        <div class="header-title">
          <h1>도로 위험 분석</h1>
          <p class="subtitle">${esc(state.originLabel)} → ${esc(state.destination)} · 전체 ${total}구간</p>
        </div>
      </header>

      <div class="scroll-area">
        <div style="padding: 14px 16px 8px;">
          <div class="composition-card">
            <p style="margin: 0; font-size: 11px; font-weight: 600; color: var(--text-secondary);">경로 구성</p>
            <div class="composition-bar">
              <div style="flex: ${safe_m}; background: var(--safety-safe);"></div>
              <div style="flex: ${warn_m}; background: var(--safety-warn);"></div>
              <div style="flex: ${danger_m}; background: var(--safety-danger);"></div>
            </div>
            <div class="composition-legend">
              <div class="composition-legend-item">
                <div class="dot-row"><span class="dot" style="background: var(--safety-safe);"></span><span>안전</span></div>
                <p class="count">${segments.safe}구간<span class="pct">${pct(safe_m)}%</span></p>
              </div>
              <div class="composition-legend-item">
                <div class="dot-row"><span class="dot" style="background: var(--safety-warn);"></span><span>주의</span></div>
                <p class="count">${segments.warn}구간<span class="pct">${pct(warn_m)}%</span></p>
              </div>
              <div class="composition-legend-item">
                <div class="dot-row"><span class="dot" style="background: var(--safety-danger);"></span><span>위험</span></div>
                <p class="count">${segments.danger}구간<span class="pct">${pct(danger_m)}%</span></p>
              </div>
            </div>
          </div>
        </div>

        <div style="padding: 8px 16px;">
          <p class="input-label" style="margin-bottom: 4px;">주의해야 할 구간</p>
          ${
            risky_roads.length
              ? `<p style="margin: 0 0 8px; font-size: 11px; color: var(--text-secondary);">
                   <i class="ti ti-map-pin" aria-hidden="true"></i> 번호는 지도 위 같은 번호의 위치예요
                 </p>`
              : ""
          }
          ${
            risky_roads.length
              ? risky_roads
                  .map(
                    (r, i) => `
            <div class="risk-card ${r.level}">
              <div class="risk-card-head" data-risk-toggle="${i}" style="cursor:pointer;">
                <span class="risk-num" style="background:${r.level === "danger" ? "#E63946" : "#F59E0B"};color:#fff;width:22px;height:22px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;font-size:12px;font-weight:700;flex-shrink:0;">${i + 1}</span>
                <span class="risk-badge ${r.level}">${r.level === "danger" ? "위험" : "주의"}</span>
                <i class="ti ti-chevron-down" id="risk-chevron-${i}" aria-hidden="true" style="margin-left:auto;font-size:14px;color:var(--text-secondary);transition:transform .15s;"></i>
              </div>
              <div id="risk-body-${i}" style="display:none;">
                <p class="risk-card-desc">${fmtBold(r.description)}</p>
                <div class="tag-row">
                  ${r.tags.map((t) => `<span class="tag"><i class="ti ${t.icon}" aria-hidden="true"></i>${esc(t.label)}</span>`).join("")}
                </div>
              </div>
            </div>
          `
                  )
                  .join("")
              : `<div class="banner banner-info">
                   <div class="banner-header"><i class="ti ti-shield-check" aria-hidden="true"></i><span>안전한 길</span></div>
                   <p class="banner-body">이 경로엔 특별히 조심할 위험·주의 구간이 없어요.</p>
                 </div>`
          }
        </div>

        <div style="padding: 6px 16px 18px;">
          <button class="btn btn-block" style="background: var(--bg-secondary);" data-action="open-map">
            <i class="ti ti-map-pin" aria-hidden="true"></i>지도에서 위치 보기
          </button>
        </div>
      </div>
    </div>
  `;
}

function renderMap() {
  const data = currentRoute();
  const decision = state.route ? decisionFor(data) : decideMode(state.remainingMin, state.safestBaselineMin);
  const { risky_roads, distance_m, duration_min, segments } = data;
  const riskyCount = risky_roads.length;

  return `
    <div class="screen active" id="screen-map">
      <div style="position: absolute; top: 12px; left: 12px; right: 12px; z-index: 10; display: flex; gap: 8px; align-items: center;">
        <button class="map-control-btn" data-action="back" aria-label="뒤로">
          <i class="ti ti-arrow-left" aria-hidden="true"></i>
        </button>
        <div style="flex: 1; background: var(--bg-primary); border: 0.5px solid var(--border-tertiary); border-radius: 18px; padding: 9px 14px;">
          <p style="font-size: 12px; font-weight: 600;">${esc(state.originLabel)} → ${esc(state.destination)}</p>
        </div>
      </div>

      <div class="map-canvas" style="flex: 1; position: relative;">
        ${
          state.route && state.route.geometry
            ? `<div id="leaflet-full" style="position:absolute;inset:0;z-index:0;"></div>`
            : renderRouteFullSvg()
        }

        <div class="map-controls" style="bottom: 240px; z-index: 600;">
          <button class="map-control-btn" data-action="toggle-map-mode" aria-label="위험도 보기"
            style="${state.mapMode === "risk" ? "background:var(--text-info);" : ""}">
            <i class="ti ti-search" aria-hidden="true" style="${state.mapMode === "risk" ? "color:#fff;" : ""}"></i>
          </button>
          <button class="map-control-btn" data-action="toggle-school-zones" aria-label="스쿨존 표시"
            style="${state.showSchoolZones ? "background:var(--text-info);" : ""}">
            <i class="ti ti-layers-intersect" aria-hidden="true" style="${state.showSchoolZones ? "color:#fff;" : ""}"></i>
          </button>
        </div>

        <div class="map-overlay map-legend" style="bottom: 240px; z-index: 600;">
          <p style="margin: 0 0 4px; font-size: 9px; color: var(--text-secondary); font-weight: 600;">안전도</p>
          <div class="legend-item"><span class="legend-line" style="background: #1D9E75;"></span><span>안전</span></div>
          <div class="legend-item"><span class="legend-line" style="background: var(--safety-warn);"></span><span>주의</span></div>
          <div class="legend-item"><span class="legend-line" style="background: var(--safety-danger);"></span><span>위험</span></div>
          ${state.showSchoolZones ? `<div class="legend-item"><span class="legend-line" style="background:#378ADD;opacity:0.9;"></span><span>스쿨존</span></div>` : ""}
        </div>
      </div>

      <div class="bottom-sheet" id="map-sheet">
        <div class="sheet-handle"></div>
        ${
          state.mapMode === "risk"
            ? riskSheetHtml()
            : `<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                 <p style="font-size: 13px; font-weight: 600;">${riskyCount > 0 ? (risky_roads.some((r) => r.level === "danger") ? "위험" : "주의") + " 구간 " + riskyCount + "곳" : "조심할 구간 없음"}</p>
                 <p style="font-size: 11px; color: var(--text-secondary);">${distance_m}m · ${duration_min}분</p>
               </div>
               ${riskyCount > 0 ? `<p style="font-size:12px;color:var(--text-secondary);margin:0 0 10px;">번호를 탭하면 위험 이유가 나와요</p>` : ""}
               <button class="btn btn-primary btn-block" data-action="start-nav">
                 <i class="ti ti-navigation" aria-hidden="true"></i>안내 시작
               </button>`
        }
      </div>
    </div>
  `;
}

// 안내(내비게이션) 화면 — GPS 추적 + 방향 지시 + 도착 모달
function renderNav() {
  const data = currentRoute();
  const { distance_m, duration_min } = data;
  const arrival = formatTime(new Date(Date.now() + duration_min * 60000));
  return `
    <div class="screen active" id="screen-nav">
      <div class="nav-instruction">
        <div class="nav-dir-icon" id="nav-dir-icon-box">
          <i class="ti ti-arrow-up" id="nav-instr-icon" aria-hidden="true"></i>
        </div>
        <div class="nav-dir-text">
          <p class="nav-dir-dist" id="nav-instr-dist">출발 준비 중…</p>
          <p class="nav-dir-action" id="nav-instr-text">경로를 따라 이동하세요</p>
          <p class="nav-dir-warn" id="nav-instr-warn" style="display:none;"></p>
        </div>
        <button class="map-control-btn" data-action="stop-nav" aria-label="안내 종료">
          <i class="ti ti-x" aria-hidden="true"></i>
        </button>
      </div>

      <div class="map-canvas" style="flex: 1; position: relative;">
        ${
          state.route && state.route.geometry
            ? `<div id="leaflet-nav" style="position:absolute;inset:0;z-index:0;"></div>`
            : renderRouteFullSvg()
        }
        <div class="map-overlay map-legend" style="bottom: 80px; z-index: 600;">
          <p style="margin: 0 0 4px; font-size: 9px; color: var(--text-secondary); font-weight: 600;">안전도</p>
          <div class="legend-item"><span class="legend-line" style="background: #1D9E75;"></span><span>안전</span></div>
          <div class="legend-item"><span class="legend-line" style="background: var(--safety-warn);"></span><span>주의</span></div>
          <div class="legend-item"><span class="legend-line" style="background: var(--safety-danger);"></span><span>위험</span></div>
        </div>
        <div style="position:absolute; right:12px; bottom:88px; z-index:600;">
          <button class="map-control-btn" id="nav-recenter" aria-label="현재 위치로">
            <i class="ti ti-current-location" aria-hidden="true"></i>
          </button>
        </div>
      </div>

      <div class="nav-offroute" id="nav-offroute" style="display:none;">
        <i class="ti ti-alert-triangle" aria-hidden="true"></i>
        경로를 벗어났어요 — 경로로 돌아와 주세요
      </div>

      <div class="nav-arrived" id="nav-arrived" style="display:none;">
        <div class="nav-arrived-card">
          <i class="ti ti-flag-3" aria-hidden="true"></i>
          <p class="nav-arrived-title">도착했어요!</p>
          <p class="nav-arrived-sub">${esc(state.destination)}에 안전하게 도착했어요</p>
          <button class="btn btn-primary btn-block" data-action="stop-nav" style="margin-top:16px;">
            안내 종료
          </button>
        </div>
      </div>

      <div class="nav-bottom">
        <div class="nav-stat">
          <p class="nav-stat-label">남은 거리</p>
          <p class="nav-stat-value" id="nav-rem-dist">${distance_m}m</p>
        </div>
        <div class="nav-stat" style="text-align:center;">
          <p class="nav-stat-label">남은 시간</p>
          <p class="nav-stat-value" id="nav-rem-time">${duration_min}분</p>
        </div>
        <div class="nav-stat" style="text-align:right;">
          <p class="nav-stat-label">도착 예정</p>
          <p class="nav-stat-value" id="nav-eta">${arrival}</p>
        </div>
      </div>
    </div>
  `;
}

// 위험도 보기 모드의 바텀시트 내용 (마커 탭 / 도로 탭 / 기본)
function riskSheetHtml() {
  // 번호 마커 탭 → 해당 구간 위험 이유
  if (state.selectedRiskyRoad) {
    const { road: r, idx: i } = state.selectedRiskyRoad;
    const lvl = r.level;
    const bg = lvl === "danger" ? "#E63946" : "#F59E0B";
    return `
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:10px;">
        <span style="background:${bg};color:#fff;width:22px;height:22px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;font-size:12px;font-weight:700;flex-shrink:0;">${i + 1}</span>
        <span class="risk-badge ${lvl}">${lvl === "danger" ? "위험" : "주의"}</span>
      </div>
      <p style="font-size:13px;line-height:1.6;color:var(--text-primary);">${fmtBold(r.description)}</p>
      ${r.tags.length ? `<div class="tag-row" style="margin-top:8px;">${r.tags.map((t) => `<span class="tag"><i class="ti ${t.icon}" aria-hidden="true"></i>${esc(t.label)}</span>`).join("")}</div>` : ""}
    `;
  }
  const sel = state.selectedEdge;
  if (sel && sel.loading) {
    return `<p style="text-align:center;color:var(--text-secondary);font-size:13px;padding:8px 0;">
              <i class="ti ti-loader-2 ti-spin" aria-hidden="true"></i> 도로 분석 중…
            </p>`;
  }
  if (sel && sel.error) {
    return `<div class="banner banner-warning"><p class="banner-body">${esc(sel.error)}</p></div>`;
  }
  if (sel && sel.facts) {
    const f = sel.facts;
    const lvl = f.band === "위험" || f.band === "매우 위험" ? "danger" : f.band === "주의" ? "warn" : "safe";
    return `<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
              <span class="risk-badge ${lvl}">${esc(f.band)}</span>
              <p style="font-size:14px;font-weight:700;">${esc(f.road_name)}</p>
            </div>
            <p style="font-size:13px;line-height:1.55;color:var(--text-primary);">${fmtBold(sel.text)}</p>`;
  }
  return `<p style="text-align:center;color:var(--text-secondary);font-size:13px;padding:8px 0;">
            <i class="ti ti-map-pin-filled" aria-hidden="true"></i> 번호를 탭하면 위험 이유가 나와요
          </p>`;
}

function getChatSubtitle() {
  if (!state.origin) return "출발지를 먼저 지정해주세요";
  if (!state.route && !state.usingDummy) return `${state.destination || "학교"}까지 경로를 찾기 전이에요`;
  return `${state.destination || "학교"}까지 경로를 조정할 수 있어요`;
}

function getChatChips() {
  if (!state.origin) {
    return ["현재 위치로 출발할게요", "지도에서 출발지를 찍을게요", "학교를 먼저 고를게요"];
  }
  if (!state.route && !state.usingDummy) {
    return ["안전한 길로 찾아줘", "빠른 길도 보고 싶어", "차 많은 길은 피하고 싶어"];
  }
  const data = currentRoute();
  const riskyCount = (data.risky_roads || []).length;
  if (riskyCount > 0) {
    return ["차 많은 길 더 피하기", "너무 오래 걸려", "위험 구간 왜 위험해?"];
  }
  return ["더 안전하게 가고 싶어", "조금 더 빠르게", "다른 경로도 비교해줘"];
}

function routeStatsLine(data) {
  const segments = data.segments || {};
  const risky = (segments.warn || 0) + (segments.danger || 0);
  const zone = Math.round((data.school_zone_ratio || 0) * 100);
  return `${data.distance_m}m · 약 ${data.duration_min}분 · 주의 구간 ${risky}곳 · 스쿨존 ${zone}%`;
}

function buildAdjustedRouteMessage(data, msgs) {
  const reason = msgs[0] || "말씀을 반영해 경로를 다시 계산했어요.";
  const mode = data.mode?.mode_label || "맞춤 경로";
  const riskyRoad = (data.risky_roads || [])[0];
  const riskNote = riskyRoad
    ? ` 특히 ${riskyRoad.name} 근처는 ${riskyRoad.level === "danger" ? "위험" : "주의"} 구간이라 지도에서 확인해보면 좋아요.`
    : " 이번 경로에는 특별히 위험한 도로 구간이 적어요.";
  return `${reason} ${mode} 기준으로 다시 보니 ${routeStatsLine(data)}예요.${riskNote}`;
}

function buildNoOriginMessage(text) {
  if (/현재\s*위치|GPS|위치/.test(text)) {
    state.originType = "current";
    return "좋아요. 현재 위치를 확인해서 출발지로 사용할게요. 위치 권한을 허용하면 바로 경로를 찾을 수 있어요.";
  }
  if (/지도|핀|찍|선택/.test(text)) {
    state.originType = "pin";
    state.originLabel = state.origin ? state.originLabel : "지도에서 출발지를 탭하세요";
    return "좋아요. 지도에서 출발지를 찍는 화면으로 이동할게요.";
  }
  if (/학교|목적지|도착/.test(text)) {
    return "도착 학교는 고를 수 있어요. 그래도 경로를 계산하려면 출발지가 먼저 필요해요.";
  }
  return "말씀하신 조건은 기억해둘게요. 먼저 출발지를 정해야 실제 통학로를 계산할 수 있어요.";
}

function chatBubble(msg) {
  if (msg.role === "user") {
    return `<div class="bubble bubble-user">${esc(msg.content)}</div>`;
  }
  const body =
    msg.content === "__typing__"
      ? `<span class="typing-dots"><span></span><span></span><span></span></span>`
      : esc(msg.content);
  return `
    <div style="display: flex; gap: 8px; align-items: flex-end;">
      <div style="width: 24px; height: 24px; border-radius: 50%; background: var(--bg-info); display: flex; align-items: center; justify-content: center; flex-shrink: 0;">
        <i class="ti ti-shield-check" style="font-size: 13px; color: var(--text-info);" aria-hidden="true"></i>
      </div>
      <div class="bubble bubble-bot" style="max-width: 86%;">${body}</div>
    </div>`;
}

async function fetchAltRoute() {
  if (!state.origin || !state.destination) return;
  const altStyle = state.style === "safe" ? "fast" : "safe";
  state.compareLoading = true;
  state.altRoute = null;
  navigate("compare");
  try {
    state.altRoute = await apiPost("/api/route", {
      lat: state.origin.lat, lon: state.origin.lon,
      grade: state.grade, style: altStyle,
      time_left_min: state.remainingMin,
      destination: state.destination,
      preferred_gate: state.preferredGate,
    });
  } catch (e) {
    state.altRoute = { _error: e.message };
  } finally {
    state.compareLoading = false;
    render();
  }
}

function renderCompare() {
  const current = state.route;
  const alt = state.altRoute;
  const curIcon  = state.style === "safe" ? "ti-shield" : "ti-bolt";
  const altIcon  = state.style === "safe" ? "ti-bolt"   : "ti-shield";
  const curLabel = state.style === "safe" ? "안전형"    : "효율형";
  const altLabel = state.style === "safe" ? "효율형"    : "안전형";

  const delta = (alt && !alt._error && current) ? {
    dist:  alt.distance_m - current.distance_m,
    dur:   alt.duration_min - current.duration_min,
    risky: (alt.risky_roads || []).length - (current.risky_roads || []).length,
    zone:  Math.round((alt.school_zone_ratio || 0) * 100) - Math.round((current.school_zone_ratio || 0) * 100),
  } : null;

  const chip = (val, lowerIsBetter, unit) => {
    if (val === 0) return `<span class="compare-delta" style="color:var(--text-secondary);">–</span>`;
    const better = lowerIsBetter ? val < 0 : val > 0;
    const color = better ? "#1d9e75" : "#e24b4a";
    return `<span class="compare-delta" style="color:${color};">${val > 0 ? "+" : ""}${val}${unit}</span>`;
  };

  const statsHtml = (r, d) => {
    const risky = (r.risky_roads || []).length;
    const zone  = Math.round((r.school_zone_ratio || 0) * 100);
    return `
      <div class="compare-stats">
        <div class="compare-stat">
          <p class="compare-stat-val">${r.distance_m}<span class="unit">m</span></p>
          ${d ? chip(d.dist, true, "m") : ""}
          <p class="compare-stat-lbl">거리</p>
        </div>
        <div class="compare-stat">
          <p class="compare-stat-val">${r.duration_min}<span class="unit">분</span></p>
          ${d ? chip(d.dur, true, "분") : ""}
          <p class="compare-stat-lbl">소요시간</p>
        </div>
        <div class="compare-stat">
          <p class="compare-stat-val">${risky}<span class="unit">곳</span></p>
          ${d ? chip(d.risky, true, "곳") : ""}
          <p class="compare-stat-lbl">위험구간</p>
        </div>
        <div class="compare-stat">
          <p class="compare-stat-val">${zone}<span class="unit">%</span></p>
          ${d ? chip(d.zone, false, "%") : ""}
          <p class="compare-stat-lbl">스쿨존</p>
        </div>
      </div>`;
  };

  const mapWrap = (id) =>
    `<div class="compare-map-wrap"><div id="${id}" style="position:absolute;inset:0;z-index:0;"></div></div>`;

  const altCardHtml = () => {
    if (state.compareLoading) return `
      <div class="compare-card" style="display:flex;align-items:center;justify-content:center;min-height:180px;">
        <i class="ti ti-loader-2 ti-spin" style="font-size:32px;color:var(--text-info);" aria-hidden="true"></i>
      </div>`;
    if (!alt || alt._error) return `
      <div class="compare-card">
        <div class="banner banner-warning"><p class="banner-body">${esc(alt?._error || "대체 경로를 계산하지 못했어요.")}</p></div>
      </div>`;
    return `
      <div class="compare-card">
        <div class="compare-card-head-row">
          <i class="ti ${altIcon}" aria-hidden="true"></i>
          <span class="compare-card-label">${esc(altLabel)}</span>
        </div>
        ${alt.geometry ? mapWrap("leaflet-compare-alt") : ""}
        ${statsHtml(alt, delta)}
        <button class="btn btn-primary btn-block" data-action="select-alt-route" style="margin-top:14px;">
          <i class="ti ti-check" aria-hidden="true"></i>이 경로로 설정
        </button>
      </div>`;
  };

  return `
    <div class="screen active" id="screen-compare">
      <header class="header">
        <button class="back" data-action="back" aria-label="뒤로"><i class="ti ti-arrow-left" aria-hidden="true"></i></button>
        <div class="header-title"><h1>경로 비교</h1></div>
      </header>
      <div class="scroll-area" style="padding:16px;display:flex;flex-direction:column;gap:12px;">
        <div class="compare-card compare-card-current">
          <div class="compare-card-head-row">
            <i class="ti ${curIcon}" aria-hidden="true"></i>
            <span class="compare-card-label">${esc(curLabel)}</span>
            <span class="compare-now-badge">현재</span>
          </div>
          ${current?.geometry ? mapWrap("leaflet-compare-current") : ""}
          ${current ? statsHtml(current, null) : ""}
          <button class="btn btn-block" data-action="back" style="margin-top:14px;">현재 경로 유지</button>
        </div>
        ${altCardHtml()}
        <div style="height:8px;"></div>
      </div>
    </div>`;
}

function renderChat() {
  return `
    <div class="screen active" id="screen-chat">
      <header class="header">
        <button class="back" data-action="back" aria-label="뒤로">
          <i class="ti ti-arrow-left" aria-hidden="true"></i>
        </button>
        <div style="width: 32px; height: 32px; border-radius: 50%; background: var(--bg-info); display: flex; align-items: center; justify-content: center;">
          <i class="ti ti-shield-check" style="font-size: 18px; color: var(--text-info);" aria-hidden="true"></i>
        </div>
        <div class="header-title">
          <h1>관악 안전통학</h1>
          <p class="subtitle">${esc(getChatSubtitle())}</p>
        </div>
      </header>

      <div class="chat-area" id="chat-area">
        ${state.chat.map(chatBubble).join("")}
        <div class="chip-row">
          ${getChatChips().map((c) => `<button class="chip" data-chip="${esc(c)}">${esc(c)}</button>`).join("")}
        </div>
      </div>

      <div class="chat-input-bar">
        <i class="ti ti-microphone" style="font-size: 20px; color: var(--text-secondary);" aria-hidden="true"></i>
        <input class="chat-input" id="chat-input" placeholder="메시지 입력..." autocomplete="off" />
        <button class="send-btn" data-action="send-chat" aria-label="전송">
          <i class="ti ti-arrow-up" aria-hidden="true"></i>
        </button>
      </div>
    </div>
  `;
}

// ===== 채팅 → /api/nudge =====
async function sendChat(text) {
  text = (text || "").trim();
  if (!text) return;
  state.chat.push({ role: "user", content: text });

  if (!state.origin) {
    const noOriginMessage = buildNoOriginMessage(text);
    state.chat.push({
      role: "assistant",
      content: noOriginMessage,
    });
    render();
    if (/현재\s*위치|GPS|위치/.test(text)) {
      navigate("input");
      acquireLocation();
    } else if (/지도|핀|찍|선택/.test(text)) {
      navigate("input");
    }
    return;
  }

  state.chat.push({ role: "assistant", content: "__typing__" });
  render();

  try {
    const d = await apiPost("/api/nudge", {
      lat: state.origin.lat,
      lon: state.origin.lon,
      grade: state.grade,
      style: state.style,
      base_style: state.baseStyle,
      time_left_min: state.remainingMin,
      cap_override: state.cap_override,
      destination: state.destination, // 대화 중에도 선택한 학교 유지
      text,
    });
    state.chat.pop(); // typing 제거
    const msgs = (d.nudge && d.nudge.messages) || [];
    // 경로/상태 갱신 (stickiness 유지)
    state.route = d;
    state.usingDummy = false;
    state.style = d.nudge.alpha_axis === "max" ? "safe" : "fast";
    state.cap_override = d.nudge.cap_override;
    // ai_response 우선 사용, 없으면 하드코딩 폴백
    const responseText = d.ai_response || buildAdjustedRouteMessage(d, msgs);
    state.chat.push({
      role: "assistant",
      content: responseText,
    });
  } catch (e) {
    if (state.chat[state.chat.length - 1]?.content === "__typing__") state.chat.pop();
    state.chat.push({ role: "assistant", content: "조정 중 문제가 생겼어요: " + e.message });
  }
  render();
}

function renderMinwon() {
  const list = state.minwonList;
  return `
    <div class="screen active" id="screen-minwon">
      <header class="header">
        <div class="header-title">
          <h1>민원 신고</h1>
          <p class="subtitle">통학로 불편사항을 신고해요</p>
        </div>
        <button class="btn btn-primary" style="flex-shrink:0;padding:8px 12px;font-size:13px;" data-action="new-minwon">
          <i class="ti ti-plus" aria-hidden="true"></i>신고
        </button>
      </header>

      <div class="scroll-area">
        ${list.length === 0 ? `
          <div style="padding:48px 20px;text-align:center;">
            <i class="ti ti-speakerphone" style="font-size:52px;color:var(--text-tertiary);display:block;margin-bottom:14px;" aria-hidden="true"></i>
            <p style="color:var(--text-secondary);font-size:14px;font-weight:600;">아직 신고한 민원이 없어요</p>
            <p style="color:var(--text-tertiary);font-size:12px;margin-top:6px;line-height:1.6;">공사 중인 길, 파손된 시설, 설치 요청 등<br>통학로 불편사항을 신고하면 관악구에 전달돼요</p>
            <button class="btn btn-primary" style="margin-top:24px;" data-action="new-minwon">
              <i class="ti ti-plus" aria-hidden="true"></i>첫 민원 신고하기
            </button>
          </div>
        ` : `
          <div style="padding:12px 16px 0;">
            ${list.slice().reverse().map((m) => {
              const cat = MINWON_CATS[m.category] || { icon: "ti-alert", color: "#888", label: m.category };
              const date = new Date(m.createdAt).toLocaleDateString("ko", { month: "long", day: "numeric" });
              return `
                <div class="minwon-card">
                  <div class="minwon-card-head">
                    <div class="minwon-cat-dot" style="background:${cat.color};">
                      <i class="ti ${cat.icon}" aria-hidden="true"></i>
                    </div>
                    <div style="flex:1;min-width:0;">
                      <p class="minwon-cat-label">${esc(cat.label)}</p>
                      ${m.subCategory ? `<p class="minwon-sub-label">${esc(m.subCategory)}</p>` : ""}
                    </div>
                    <span class="minwon-status">접수됨</span>
                  </div>
                  ${m.description ? `<p class="minwon-desc">${esc(m.description)}</p>` : ""}
                  ${m.photoCount ? `
                    <p style="font-size:11px;color:var(--text-secondary);margin:0 0 6px;display:flex;align-items:center;gap:4px;">
                      <i class="ti ti-photo" style="font-size:11px;" aria-hidden="true"></i>사진 ${m.photoCount}장
                    </p>` : ""}
                  <div class="minwon-meta">
                    <i class="ti ti-map-pin" style="font-size:11px;flex-shrink:0;" aria-hidden="true"></i>
                    <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(m.locationLabel || "위치 미지정")}</span>
                    <span class="minwon-date">${date}</span>
                  </div>
                </div>`;
            }).join("")}
          </div>
          <div style="height:16px;"></div>
        `}
      </div>

      <nav class="bottom-nav">
        <button data-action="go-home" aria-label="홈">
          <i class="ti ti-home" aria-hidden="true"></i><span>홈</span>
        </button>
        <button data-action="chat" aria-label="대화">
          <i class="ti ti-message" aria-hidden="true"></i><span>대화</span>
        </button>
        <button class="active" aria-label="민원">
          <i class="ti ti-speakerphone" aria-hidden="true"></i><span>민원</span>
        </button>
        <button aria-label="설정">
          <i class="ti ti-settings" aria-hidden="true"></i><span>설정</span>
        </button>
      </nav>
    </div>
  `;
}

function renderMinwonForm() {
  const d = state.minwonDraft;
  const catKeys = Object.keys(MINWON_CATS);
  const photoRequired = d.category === "불량";
  const photoOk = !photoRequired || d.photoUrls.length > 0;
  const canSubmit = d.category && d.location && photoOk;

  return `
    <div class="screen active" id="screen-minwon-form">
      <header class="header">
        <button class="back" data-action="back" aria-label="뒤로">
          <i class="ti ti-arrow-left" aria-hidden="true"></i>
        </button>
        <div class="header-title">
          <h1>민원 신고</h1>
        </div>
      </header>

      <div class="scroll-area" style="padding:16px;">

        <p class="input-label">신고 유형</p>
        <div style="display:flex;flex-direction:column;gap:8px;margin-bottom:18px;">
          ${catKeys.map((key) => {
            const cat = MINWON_CATS[key];
            const active = d.category === key;
            return `
              <button class="minwon-cat-btn${active ? " active" : ""}" data-minwon-cat="${key}"
                style="${active ? `border-color:${cat.color};background:${cat.bg};` : ""}">
                <div class="minwon-cat-icon" style="background:${active ? cat.color : "var(--bg-tertiary)"};">
                  <i class="ti ${cat.icon}" style="color:${active ? "#fff" : "var(--text-secondary)"};" aria-hidden="true"></i>
                </div>
                <div style="flex:1;text-align:left;">
                  <p style="font-size:14px;font-weight:600;margin:0;color:var(--text-primary);">${esc(cat.label)}</p>
                  <p style="font-size:11px;color:var(--text-secondary);margin:2px 0 0;">${cat.subs.slice(0, 3).join(" · ")}</p>
                </div>
                ${active ? `<i class="ti ti-check" style="color:${cat.color};font-size:18px;flex-shrink:0;" aria-hidden="true"></i>` : ""}
              </button>`;
          }).join("")}
        </div>

        ${d.category ? `
          <p class="input-label">세부 유형</p>
          <div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:18px;">
            ${MINWON_CATS[d.category].subs.map((sub) => `
              <button class="chip${d.subCategory === sub ? " active" : ""}" data-minwon-sub="${esc(sub)}">${esc(sub)}</button>
            `).join("")}
          </div>
        ` : ""}

        <p class="input-label">위치</p>
        <div style="position:relative;height:180px;border-radius:var(--radius-md);overflow:hidden;margin-bottom:6px;border:0.5px solid var(--border-tertiary);">
          ${d.location
            ? `<div id="leaflet-minwon" style="position:absolute;inset:0;z-index:0;"></div>`
            : `<div style="height:100%;background:var(--bg-tertiary);display:flex;align-items:center;justify-content:center;flex-direction:column;gap:8px;">
                 <i class="ti ti-map-pin" style="font-size:28px;color:var(--text-tertiary);" aria-hidden="true"></i>
                 <p style="font-size:12px;color:var(--text-secondary);margin:0;">아래 버튼으로 위치를 설정해주세요</p>
               </div>`
          }
          <div style="position:absolute;bottom:8px;right:8px;z-index:10;">
            <button class="map-control-btn" data-action="minwon-gps" aria-label="현재 위치">
              <i class="ti ti-current-location" aria-hidden="true"></i>
            </button>
          </div>
        </div>
        <p id="minwon-loc-label" style="font-size:12px;color:var(--text-secondary);margin:0 0 18px;display:flex;align-items:center;gap:4px;">
          <i class="ti ti-map-pin" style="font-size:11px;" aria-hidden="true"></i>
          ${esc(d.locationLabel || "위치 미지정 — 현재 위치 버튼을 누르거나 지도를 탭해 수정하세요")}
        </p>

        <p class="input-label">
          사진
          ${photoRequired
            ? `<span style="color:var(--text-danger);font-weight:600;margin-left:4px;">필수</span>`
            : `<span style="color:var(--text-tertiary);font-weight:400;">(선택)</span>`}
        </p>
        <input type="file" id="minwon-photo-input" accept="image/*" multiple capture="environment" style="display:none;" />

        ${d.photoUrls.length > 0 ? `
          <div class="minwon-photo-grid">
            ${d.photoUrls.map((url, i) => `
              <div class="minwon-photo-thumb">
                <img src="${url}" alt="첨부 사진 ${i + 1}" />
                <button class="minwon-photo-del" data-photo-idx="${i}" aria-label="삭제">
                  <i class="ti ti-x" aria-hidden="true"></i>
                </button>
              </div>
            `).join("")}
            ${d.photoUrls.length < 3 ? `
              <button class="minwon-photo-add" data-action="add-photo" aria-label="사진 추가">
                <i class="ti ti-camera-plus" aria-hidden="true"></i>
                <span>추가</span>
              </button>
            ` : ""}
          </div>
        ` : `
          <button class="minwon-photo-upload${photoRequired ? " required" : ""}" data-action="add-photo">
            <i class="ti ti-camera" aria-hidden="true"></i>
            <span>${photoRequired ? "사진 추가 (필수)" : "사진 추가"}</span>
          </button>
        `}

        ${photoRequired && !d.photoUrls.length ? `
          <p style="font-size:11px;color:var(--text-danger);margin:4px 0 14px;display:flex;align-items:center;gap:4px;">
            <i class="ti ti-alert-circle" style="font-size:11px;" aria-hidden="true"></i>
            시설물 불량 신고는 현장 사진이 필요해요
          </p>
        ` : `<div style="height:14px;"></div>`}

        <p class="input-label">상황 설명 <span style="color:var(--text-tertiary);font-weight:400;">(선택)</span></p>
        <textarea id="minwon-desc" class="text-input"
          placeholder="어떤 상황인지 자세히 적어주시면 처리에 도움이 돼요"
          style="width:100%;resize:none;height:80px;">${esc(d.description || "")}</textarea>

        <div style="height:16px;"></div>
      </div>

      <div class="action-bar">
        <button class="btn btn-primary btn-block" data-action="submit-minwon"
          ${!canSubmit ? `disabled style="opacity:0.45;"` : ""}>
          <i class="ti ti-send" aria-hidden="true"></i>
          ${!d.category ? "유형을 선택해주세요"
            : !d.location ? "위치를 설정해주세요"
            : !photoOk ? "사진을 추가해주세요 (필수)"
            : "민원 제출"}
        </button>
      </div>
    </div>
  `;
}

// ===== 라우터 =====
const SCREENS = {
  profile: renderProfile,
  home: renderHome,
  input: renderInput,
  result: renderResult,
  risk: renderRiskDetail,
  map: renderMap,
  nav: renderNav,
  chat: renderChat,
  compare: renderCompare,
  minwon: renderMinwon,
  "minwon-form": renderMinwonForm,
};

function render() {
  destroyMaps(); // 이전 화면의 Leaflet 인스턴스 정리 (innerHTML 교체 전)
  const app = document.getElementById("app");
  const renderer = SCREENS[state.currentScreen] || renderHome;
  app.innerHTML = `<div class="viewport">${renderer()}</div>`;
  attachEvents();
  mountMaps();
}

// ===== 이벤트 ===== (이벤트 위임)
// #app 노드는 render() 사이에도 유지되므로, 위임 클릭 리스너는 단 한 번만 등록한다.
// (매 render 마다 등록하면 리스너가 누적돼 한 번의 탭이 handleAction 을 여러 번
//  호출 → back() 이 여러 번 실행돼 메인까지 튕기는 버그가 났다.)
let _clickDelegated = false;
let _riskToggleDelegated = false;
function attachEvents() {
  const app = document.getElementById("app");

  if (!_clickDelegated) {
    app.addEventListener("click", (e) => {
      const target = e.target.closest("[data-action]");
      if (!target) return;
      const action = target.dataset.action;
      handleAction(action, target, e);
    });
    _clickDelegated = true;
  }

  if (!_riskToggleDelegated) {
    app.addEventListener("click", (e) => {
      const target = e.target.closest("[data-risk-toggle]");
      if (!target) return;
      const idx = target.dataset.riskToggle;
      const body = document.getElementById(`risk-body-${idx}`);
      const chevron = document.getElementById(`risk-chevron-${idx}`);
      if (!body) return;
      const open = body.style.display !== "none";
      body.style.display = open ? "none" : "";
      if (chevron) chevron.style.transform = open ? "" : "rotate(180deg)";
    });
    _riskToggleDelegated = true;
  }

  // 채팅: Enter 전송 + 칩 + 자동 스크롤
  const chatInput = document.getElementById("chat-input");
  if (chatInput) {
    chatInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        const v = chatInput.value;
        chatInput.value = "";
        sendChat(v);
      }
    });
  }
  app.querySelectorAll("[data-chip]").forEach((btn) => {
    btn.addEventListener("click", () => sendChat(btn.dataset.chip));
  });

  // 도착지 드롭다운 선택
  app.querySelectorAll("[data-school]").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.destination = btn.dataset.school;
      state.preferredGate = null; // 학교 바뀌면 출입문 선택 초기화
      state.destMenuOpen = false;
      render();
    });
  });

  // 프로필: 학년 / 스타일 선택
  app.querySelectorAll("[data-grade]").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.grade = parseInt(btn.dataset.grade, 10);
      if (state.grade <= 3) {
        state.style = "safe";
        state.baseStyle = "safe";
      }
      render();
    });
  });
  app.querySelectorAll("[data-style]").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (btn.disabled) return;
      state.style = btn.dataset.style;
      state.baseStyle = btn.dataset.style;
      render();
    });
  });

  // 프로필: 역할(부모/아이) 선택
  app.querySelectorAll("[data-role]").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.role = btn.dataset.role;
      render();
    });
  });

  // 프로필: 이름 입력 (재렌더로 포커스 잃지 않게 state만 갱신)
  const nameInput = document.getElementById("child-name");
  if (nameInput) {
    nameInput.addEventListener("input", (e) => {
      state.childName = e.target.value;
    });
  }
  // 민원 카테고리 선택
  app.querySelectorAll("[data-minwon-cat]").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.minwonDraft.category = btn.dataset.minwonCat;
      state.minwonDraft.subCategory = null;
      render();
    });
  });

  // 민원 세부유형 선택 (재렌더 없이 상태·UI만 토글)
  app.querySelectorAll("[data-minwon-sub]").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.minwonDraft.subCategory = btn.dataset.minwonSub;
      app.querySelectorAll("[data-minwon-sub]").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      // 제출 버튼 상태 갱신
      const submitBtn = document.querySelector("[data-action='submit-minwon']");
      if (submitBtn && state.minwonDraft.location) {
        submitBtn.disabled = false;
        submitBtn.style.opacity = "";
      }
    });
  });

  // 민원 사진 파일 선택
  const photoInput = document.getElementById("minwon-photo-input");
  if (photoInput) {
    photoInput.addEventListener("change", (e) => {
      const files = Array.from(e.target.files || []);
      files.forEach((file) => {
        if (state.minwonDraft.photoUrls.length >= 3) return;
        state.minwonDraft.photoFiles.push(file);
        state.minwonDraft.photoUrls.push(URL.createObjectURL(file));
      });
      e.target.value = ""; // 동일 파일 재선택 허용
      render();
    });
  }

  // 민원 사진 삭제
  app.querySelectorAll("[data-photo-idx]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const idx = parseInt(btn.dataset.photoIdx, 10);
      URL.revokeObjectURL(state.minwonDraft.photoUrls[idx]);
      state.minwonDraft.photoUrls.splice(idx, 1);
      state.minwonDraft.photoFiles.splice(idx, 1);
      render();
    });
  });

  // 민원 설명 (재렌더 없이)
  const minwonDescEl = document.getElementById("minwon-desc");
  if (minwonDescEl) {
    minwonDescEl.addEventListener("input", (e) => {
      state.minwonDraft.description = e.target.value;
    });
  }

  const chatArea = document.getElementById("chat-area");
  if (chatArea) chatArea.scrollTop = chatArea.scrollHeight;

  // 내비게이션: 현재 위치로 재중심
  const recenter = document.getElementById("nav-recenter");
  if (recenter) {
    recenter.addEventListener("click", () => {
      if (navState.currentPos && _maps.length) {
        _maps[_maps.length - 1].setView(navState.currentPos, 17);
      }
    });
  }

  // 시간 슬라이더는 input 이벤트로
  const slider = document.getElementById("time-slider");
  if (slider) {
    slider.addEventListener("input", (e) => {
      state.remainingMin = parseInt(e.target.value, 10);
      updateModePreview();
    });
  }

  // 출발지 타입 세그먼트
  app.querySelectorAll("[data-origin-type]").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.originType = btn.dataset.originType;
      if (state.originType === "current") {
        acquireLocation(); // 실제 GPS 좌표 획득 (내부에서 render)
      } else if (state.originType === "pin") {
        state.originLabel = state.origin ? state.originLabel : "지도에서 출발지를 탭하세요";
        navigate("input", { replace: true }); // 핀 지도 마운트
      } else {
        state.originLabel = state.origin ? state.originLabel : "아파트명이나 주소를 입력하세요";
        state.manualMessage = state.manualMessage || "아파트 동까지 입력해도 되고, 안 나오면 단지 위치를 잡은 뒤 핀을 옮겨주세요.";
        navigate("input", { replace: true });
      }
    });
  });

  const manualInput = document.getElementById("manual-origin-input");
  if (manualInput) {
    manualInput.addEventListener("input", (e) => {
      state.manualQuery = e.target.value;
    });
    manualInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        searchManualOrigin();
      }
    });
  }
}

function updateModePreview() {
  const decision = decideMode(state.remainingMin, state.safestBaselineMin);
  const arrivalTime = new Date(Date.now() + state.remainingMin * 60000);

  // 시간 값 업데이트
  const timeValue = document.getElementById("time-value");
  if (timeValue) timeValue.textContent = state.remainingMin;

  // 도착시각 업데이트
  const arrival = document.querySelector(".time-display .arrival");
  if (arrival) arrival.textContent = `${formatTime(arrivalTime)} 도착 기준`;

  // 모드 미리보기 배너 업데이트
  const preview = document.getElementById("mode-preview");
  if (!preview) return;
  preview.className = `banner ${decision.bannerClass}`;
  preview.innerHTML = `
    <div class="banner-header">
      <i class="ti ${decision.icon}" aria-hidden="true"></i>
      <span>${esc(decision.modeLabel)} 모드</span>
    </div>
    <p class="banner-body">${esc(decision.explanation)}</p>
  `;
}

// ===== 위치 획득 (geolocation) =====
async function acquireLocation() {
  state.error = null;
  state.loading = true;
  state.originLabel = "위치 확인 중…";
  if (state.currentScreen === "input") render();
  try {
    const pos = await getCurrentPosition();
    state.origin = pos;
    state.originLabel = "현재 위치";
    state.clampedToGwanak = false;
    await resolveDestination(pos.lat, pos.lon); // 학구 추천 도착지 (render 전 state 확정)
    // 현재 위치가 관악구(학구) 밖이면 → 더미 폴백 대신 관악구 기준점으로 GPS 고정
    if (!state.autoDestination) {
      state.origin = { ...GWANAK_FALLBACK };
      state.originLabel = "관악구 기준 위치 (현재 위치가 관악구 밖이라 고정했어요)";
      state.clampedToGwanak = true;
      await resolveDestination(GWANAK_FALLBACK.lat, GWANAK_FALLBACK.lon);
    }
  } catch (e) {
    state.origin = null;
    state.clampedToGwanak = false;
    state.originLabel = e.message;
  } finally {
    state.loading = false;
    if (state.currentScreen === "input") render();
  }
}

async function searchManualOrigin() {
  const q = state.manualQuery.trim();
  if (!q) {
    state.manualMessage = "아파트명이나 주소를 입력해주세요.";
    render();
    return;
  }
  state.manualSearching = true;
  state.manualMessage = "주소를 검색하는 중이에요…";
  if (state.currentScreen === "input") render();
  try {
    const hit = await geocodeOriginQuery(q);
    if (!hit) {
      state.origin = null;
      state.originLabel = "검색 결과 없음";
      state.manualMessage = "검색 결과를 찾지 못했어요. 아파트명, 도로명, 지번을 조금 더 구체적으로 입력해보세요.";
      return;
    }
    state.origin = { lat: hit.lat, lon: hit.lon };
    state.originLabel = hit.title || hit.address || q;
    state.clampedToGwanak = false;
    state.route = null;
    state.manualMessage = hit.exact
      ? "검색된 위치를 지도에 표시했어요. 실제 동 위치와 다르면 지도를 탭해 핀을 옮기세요."
      : "동/세부 주소까지는 정확히 찾지 못해 단지 위치를 표시했어요. 지도를 탭해 핀을 옮길 수 있어요.";
    await resolveDestination(hit.lat, hit.lon);
  } catch (e) {
    state.manualMessage = "주소 검색 중 문제가 생겼어요. 잠시 뒤 다시 시도해주세요.";
  } finally {
    state.manualSearching = false;
    if (state.currentScreen === "input") render();
  }
}

// ===== 경로 찾기 (백엔드 호출) =====
async function findRoute() {
  if (state.loading) return; // 중복 제출 방지 (앱이 무거울 때 연타 방지)

  // 좌표가 없으면 (현재위치 모드인데 미획득) 먼저 위치 시도
  if (!state.origin && state.originType === "current") {
    await acquireLocation();
  }
  if (!state.origin) {
    // 좌표 없음 → 출발지부터 정하도록 안내
    state.route = null;
    state.usingDummy = false;
    state.error = "출발지를 먼저 지정해주세요. 현재 위치를 허용하거나 ‘지도에서’ 탭해 출발지를 정하세요.";
    navigate("result");
    return;
  }

  state.loading = true;
  state.error = null;
  state.usingDummy = false;
  navigate("result"); // 로딩 화면 먼저 보여주고 채움
  try {
    const data = await apiPost("/api/route", {
      lat: state.origin.lat,
      lon: state.origin.lon,
      grade: state.grade,
      style: state.style,
      time_left_min: state.remainingMin,
      destination: state.destination,
      preferred_gate: state.preferredGate,
    });
    state.route = data;
    state.usingDummy = false;
    state.error = null;
    state.destination = data.destination?.name || state.destination;
    if (data.origin?.snapped) {
      state.safestBaselineMin = data.duration_min || state.safestBaselineMin;
    }
  } catch (e) {
    state.route = null;
    if (e.status === 0) {
      // 네트워크/서버 다운 → 데모 더미로 폴백 (데모 끊김 방지)
      state.usingDummy = true;
      state.error = e.message;
    } else {
      // 서버는 정상 — 위치/입력 문제(422 등). 실제 안내 메시지를 그대로 보여주고 고치도록 유도
      state.usingDummy = false;
      state.error = e.message;
    }
  } finally {
    state.loading = false;
    render();
  }
}

function handleAction(action, el) {
  switch (action) {
    case "back":
      back();
      break;
    case "quick-route":
    case "open-route":
    case "new-route":
      navigate("input");
      // 현재위치 모드인데 아직 좌표가 없으면 진입과 함께 GPS 시도
      if (state.originType === "current" && !state.origin) acquireLocation();
      break;
    case "find-route":
      findRoute();
      break;
    case "geocode-origin":
      searchManualOrigin();
      break;
    case "retry-location":
      acquireLocation();
      break;
    case "fix-origin":
      // 경로 실패 화면 → 지도에서 출발지 다시 찍기
      state.error = null;
      state.originType = "pin";
      navigate("input");
      break;
    case "open-map":
      state.mapMode = "route";
      state.selectedEdge = null;
      state.selectedRiskyRoad = null;
      navigate("map");
      break;
    case "start-nav":
      // 경로가 있어야 안내 가능 (없으면 무시)
      if (!state.route && !state.usingDummy) break;
      navigate("nav");
      break;
    case "stop-nav":
      stopNavigation();
      back();
      break;
    case "toggle-map-mode":
      state.mapMode = state.mapMode === "risk" ? "route" : "risk";
      state.selectedEdge = null;
      render();
      break;
    case "toggle-school-zones":
      state.showSchoolZones = !state.showSchoolZones;
      render();
      break;
    case "select-gate":
      state.preferredGate = el.dataset.gateType || null;
      findRoute();
      break;
    case "compare-routes":
      fetchAltRoute();
      break;
    case "select-alt-route":
      if (state.altRoute && !state.altRoute._error) {
        state.style = state.style === "safe" ? "fast" : "safe";
        state.baseStyle = state.style;
        state.safestBaselineMin = state.altRoute.duration_min || state.safestBaselineMin;
        state.route = state.altRoute;
        state.altRoute = null;
      }
      navigate("result", { replace: true });
      break;
    case "toggle-dest-menu":
      state.destMenuOpen = !state.destMenuOpen;
      if (state.destMenuOpen) loadSchools();
      render();
      break;
    case "risk-detail":
      navigate("risk");
      break;
    case "chat":
      navigate("chat");
      break;
    case "send-chat": {
      const input = document.getElementById("chat-input");
      if (input) {
        const v = input.value;
        input.value = "";
        sendChat(v);
      }
      break;
    }
    case "profile":
      navigate("profile");
      break;
    case "minwon":
      navigate("minwon");
      break;
    case "new-minwon":
      state.minwonDraft = { category: null, subCategory: null, location: null, locationLabel: "", description: "", photoFiles: [], photoUrls: [] };
      navigate("minwon-form");
      break;
    case "minwon-gps":
      acquireMinwonLocation();
      break;
    case "add-photo":
      document.getElementById("minwon-photo-input")?.click();
      break;
    case "submit-minwon": {
      const descEl = document.getElementById("minwon-desc");
      if (descEl) state.minwonDraft.description = descEl.value.trim();
      const d = state.minwonDraft;
      if (!d.category || !d.location) break;
      if (d.category === "불량" && !d.photoUrls.length) break;
      const { photoFiles, photoUrls, ...draftData } = d;
      // object URL 해제 (메모리 정리)
      photoUrls.forEach((u) => URL.revokeObjectURL(u));
      const complaint = { ...draftData, photoCount: photoUrls.length, createdAt: Date.now(), id: Date.now() };
      state.minwonList.push(complaint);
      saveMinwon(state.minwonList);
      state.minwonDraft = { category: null, subCategory: null, location: null, locationLabel: "", description: "", photoFiles: [], photoUrls: [] };
      navigate("minwon", { replace: true });
      break;
    }
    case "go-home":
      state.history = ["home"];
      state.currentScreen = "home";
      render();
      break;
    case "save-profile":
      state.childName = (state.childName || "").trim() || "서연"; // 비워두면 기본값
      state.profileSet = true;
      saveProfile();
      state.currentScreen = "home";
      state.history = ["home"];
      render();
      break;
  }
}

// ===== PWA: 서비스워커 등록 =====
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("sw.js").catch(() => {
      // 로컬에서는 실패할 수 있음, 무시
    });
  });
}

// ===== 부팅 =====
loadProfile(); // 저장된 프로필 적용 (없으면 프로필 설정 화면으로)
render();
loadSchools(); // 도착지 드롭다운 목록 미리 로드
