# 구동 매뉴얼 (RUNBOOK)

작성일: 2026-09-17
검증 환경: Windows 11 Education 24H2 + WSL2 Ubuntu 24.04 / RTX 4070 SUPER 12GB / i7-14700K / RAM 128GB

이 문서는 **실제로 끝까지 구동에 성공한 구성**을 기준으로 작성했습니다.
구축 과정에서 적용한 코드 수정은 [SETUP_FIXES.md](SETUP_FIXES.md)를 참고하세요.

---

## 0. 시스템 구조 — 먼저 이해할 것

이 프로젝트는 **하나의 OS에서 돌지 않습니다.** Windows와 WSL2에 역할이 나뉜 하이브리드 구조입니다.

```
┌─────────────────── Windows 11 (네이티브) ────────────────────┐
│  Isaac Sim 6.1 ── isaacsim_scripts/three_robot_tower.py       │
│    3x Franka FR3 + 블록 9개 + 오버헤드 카메라                    │
│    RTX/Vulkan 필요 → WSL2 안에서는 실행 불가                     │
│  Node.js ── gemini_web_gui (Express :3001 + Vite :5173)        │
└────────────────────────────┬──────────────────────────────────┘
                             │ FastDDS UDP 7400-7500
┌────────────────────────────┴── WSL2 Ubuntu 24.04 ─────────────┐
│  ROS 2 Jazzy ── wsl_ws/src/isaac_ros2_control                 │
│    gemini_robotics_node  : Gemini VLA 에이전트 루프             │
│    multi_robot_controller: 50Hz FSM, IK, 블록 적재              │
│    rosbridge_websocket :9090 ← 웹 대시보드 연결점                │
└───────────────────────────────────────────────────────────────┘
```

**Isaac Sim은 반드시 Windows 네이티브, ROS 2는 WSL2.** 둘은 DDS(UDP)로 통신합니다.

데이터 흐름:
```
오버헤드 카메라 ──/overhead_camera/rgb──▶ gemini_robotics_node
                                              │ Gemini API (도구 호출)
                                              ▼
                                        /gemini/action  (JSON)
                                              ▼
                                      multi_robot_controller
                                              │ IK → 관절 목표
                                              ▼
                              /fr3_{1,2,3}/joint_commands ──▶ Isaac Sim
```

---

## 1. 요구 사양

| 항목 | 요구 | 검증 환경 |
|---|---|---|
| OS (호스트) | Windows 11 | 11 Education 24H2 (빌드 26100) |
| OS (게스트) | Ubuntu 24.04 (WSL2) | 24.04.1 LTS |
| GPU | NVIDIA RTX, VRAM 10GB+ | RTX 4070 SUPER 12.88GB |
| NVIDIA 드라이버 | **580.88 이상** | 616.92 |
| CPU / RAM | 8코어+ / 32GB+ | i7-14700K 20C / 128GB |
| 디스크 | 50GB+ | Isaac Sim 6.1 압축 해제 시 약 25GB |
| Isaac Sim | **6.1.0** | 6.1.0-rc.26 |
| ROS 2 | Jazzy Jalisco | ✓ |
| Node.js | 20 LTS+ | 24.19.0 |
| Gemini API 키 | AI Studio 무료 티어 가능 | ✓ |

### ⚠️ 드라이버 버전은 타협하지 마세요

드라이버 **561.17**에서는 Isaac Sim이 `rtx.scenedb.plugin.dll`에서
**액세스 위반으로 재현성 있게 크래시**합니다. 씬이 없는 최소 스크립트조차 죽습니다.

```
000: rtx.scenedb.plugin.dll!carbOnPluginStartup+0x252db
```

Isaac Sim 내장 호환성 검사기(`isaac-sim.compatibility_check.bat`)는
최소 드라이버를 537.58로 보고 **`PASSED`를 출력하지만, 이 값은 실제 RTX 런타임 요구와 맞지 않습니다.**
검사기 통과를 근거로 삼지 마세요.

### ⚠️ Isaac Sim 버전

README는 `4.5+ 또는 6.0+`를 명시합니다. **6.x 계열을 쓰세요.**

- 코드가 사용하는 API(`isaacsim.core.experimental.utils`, `usd.schema.isaac.robot_schema`)는 4.5보다 신형입니다.
- **5.1.0은 드라이버 616.92 환경에서 위 RTX 크래시가 발생합니다.** 6.1.0에서는 발생하지 않습니다
  (동일 조건 3회 연속 검증, 셰이더 캐시 재사용 고속 실행 포함).

---

## 2. 설치

### Step 1 — NVIDIA 드라이버

580.88 이상 설치 후 **재부팅**. 확인:
```powershell
nvidia-smi --query-gpu=name,driver_version --format=csv,noheader
```

### Step 2 — Isaac Sim 6.1

```powershell
# 다운로드 (약 9.9GB)
curl -L -o D:\isaac-sim-6.1.0.zip https://downloads.isaacsim.nvidia.com/isaac-sim-standalone-6.1.0-windows-x86_64.zip

# 무결성 확인 (공개 MD5: a07968e980072c9ca27b2166443e2d89)
Get-FileHash D:\isaac-sim-6.1.0.zip -Algorithm MD5

# 압축 해제 — tar가 Expand-Archive보다 훨씬 빠릅니다 (약 4분 vs 10분+)
mkdir D:\isaacsim61
tar.exe -xf D:\isaac-sim-6.1.0.zip -C D:\isaacsim61
```

환경변수 등록 (`launcher.bat`이 이 값을 최우선으로 탐색합니다):
```powershell
[System.Environment]::SetEnvironmentVariable("ISAAC_SIM_PATH", "D:\isaacsim61", "User")
```

예제 링크 생성 (선택, 데모와 무관):
```powershell
# post_install.bat은 관리자 권한을 요구하므로 Junction으로 대체 가능
New-Item -ItemType Junction -Path "D:\isaacsim61\extension_examples" `
  -Target "D:\isaacsim61\exts\isaacsim.examples.interactive\isaacsim\examples\interactive"
```

### Step 3 — Node.js

```powershell
winget install --id OpenJS.NodeJS.LTS -e
# 새 터미널에서
node -v
```

### Step 4 — ROS 2 Jazzy (WSL2)

WSL 터미널에서 실행합니다. **sudo 비밀번호는 Ubuntu 계정 비밀번호**입니다(Windows 로그인과 별개).

```bash
cd /mnt/c/Users/<사용자>/Documents/Github/IsaacSim_GeminiRobotics/wsl_ws

bash setup_all.sh --phase 1    # 기본 도구, X11, Python
bash setup_all.sh --phase 3    # ROS 2 Jazzy + MoveIt/Nav2/control (30~60분)
bash setup_all.sh --phase 5    # FastDDS 브리지 설정
```

> **Phase 2(Docker)와 Phase 4(Isaac ROS)는 건너뜁니다.** 이 데모는 사용하지 않으며 수십 GB를 소모합니다.

**스크립트가 설치하지 않는 패키지를 수동으로 추가합니다** (없으면 Gemini 모드와 웹 GUI가 동작하지 않습니다):

```bash
sudo apt install -y ros-jazzy-rosbridge-suite ros-jazzy-cv-bridge python3-numpy python3-opencv
pip install --break-system-packages google-genai
```

### Step 5 — Gemini API 키

[aistudio.google.com/apikey](https://aistudio.google.com/apikey)에서 발급 후:

```bash
mkdir -p private
sed '1s/^\xEF\xBB\xBF//' .env.example > private/.env    # BOM 제거
```

`private/.env`의 `GEMINI_API_KEY=` 값을 실제 키로 교체합니다.
`LLM_API_KEY`와 `GEMINI_API_KEY` 중 아무 이름이나 인식하며, 자리표시자 값은 무시됩니다.

`private/`는 `.gitignore`에 포함되어 있습니다.

### Step 6 — 방화벽 (관리자 PowerShell)

```powershell
New-NetFirewallRule -DisplayName "ROS2 DDS (Isaac Sim) - Inbound" `
  -Direction Inbound -Protocol UDP -LocalPort 7400-7500 -Action Allow -Profile Any
New-NetFirewallRule -DisplayName "ROS2 DDS (Isaac Sim) - Outbound" `
  -Direction Outbound -Protocol UDP -LocalPort 7400-7500 -Action Allow -Profile Any
```

> `launcher.bat`의 방화벽 메뉴는 `protocol=ANY`로 **모든 인바운드를 허용**하므로 쓰지 마세요.

### Step 7 — 웹 대시보드 의존성

```powershell
cd gemini_web_gui
npm ci
```

### Step 8 — ROS 2 워크스페이스 빌드

```bash
# Windows 마운트 → WSL 워크스페이스로 소스 동기화
mkdir -p ~/catkin_ws/src
rsync -ru --delete /mnt/c/.../IsaacSim_GeminiRobotics/wsl_ws/src/ ~/catkin_ws/src/
cp /mnt/c/.../IsaacSim_GeminiRobotics/wsl_ws/bringup.bash ~/catkin_ws/
chmod +x ~/catkin_ws/src/isaac_ros2_control/scripts/*

cd ~/catkin_ws
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install
```

> `bringup.bash`는 워크스페이스를 동기화하지만 **빌드는 하지 않습니다.** 최초 1회는 직접 빌드해야 합니다.

---

## 3. 실행

**순서가 중요합니다.** Isaac Sim이 `/clock`을 발행해야 ROS 노드가 `use_sim_time`으로 동작합니다.

### 1) Windows — Isaac Sim

```
scripts\launcher.bat
```
메뉴에서 `three_robot_tower.py`를 선택합니다.
FR3 3대와 블록 9개가 로드되고, 오버헤드 카메라가 ROS 2로 발행을 시작합니다.

`launcher.bat`이 내부적으로 `setup_fastdds_wsl.py`를 실행해
WSL2/Windows IP를 탐지하고 FastDDS 프로파일을 양쪽에 씁니다.

### 2) WSL2 — 컨트롤러

```bash
bash wsl_ws/bringup.bash
```
메뉴에서 **1) Gemini** 선택 → rosbridge와 Gemini 컨트롤러가 함께 뜹니다.

정상 기동 시 로그:
```
[gemini_robotics_node] Gemini API client initialized.
[gemini_robotics_node] Using model: gemini-robotics-er-2-preview
[gemini_robotics_node] Gemini Robotics Node started (Function Calling mode).
[multi_robot_controller] MultiRobotController initialized. Mode: [GEMINI].
```

> `"Waiting for joint states and TF frames..."`는 초기화 완료 안내 메시지이지 **대기 상태가 아닙니다.**

### 3) Windows — 웹 대시보드

```
scripts\start_dashboard.bat
```
**반드시 `scripts` 폴더 안에서 실행**하세요 (상대 경로에 의존합니다).
Express(:3001)와 Vite(:5173)가 뜨고 브라우저가 열립니다.
음성 입력은 Web Speech API를 쓰므로 Chrome 또는 Edge를 사용하세요.

### 4) 작업 지시

브라우저에서 자연어로 입력하거나, 터미널에서 직접 호출합니다.

```bash
ros2 service call /gemini/plan_task std_srvs/srv/Trigger
```

에이전트 루프가 시작되면 다음과 같이 진행됩니다:
```
[AGENT] Starting Agentic Loop...
[MULTI-AGENT] Starting Brainstorming...
[AGENT] Agentic Turn 1/45
[TOOL] Executing: detect_objects with args {}
[GEMINI ACTION] Received: {"action":"pick","robot":"FR3_3","target":"Block8"}
[GEMINI ACTION] Received: {"action":"place","robot":"FR3_1","x":0,"y":0}
Tower height incremented to: 1
```

---

## 4. 검증

각 계층을 아래에서 위로 확인하면 문제를 빠르게 좁힐 수 있습니다.

### 4-1. Isaac Sim 단독

```powershell
# 씬 없이 최소 기동 — RTX 크래시 여부만 확인
D:\isaacsim61\python.bat -c "from isaacsim import SimulationApp; a=SimulationApp({'headless':True}); print('OK'); a.close()"
```

데모 자체 검증:
```
three_robot_tower.py --headless --test
```
기대 출력:
```
[VERIFY] All 3 robots exist on the stage.
[VERIFY] Spawners generated all 9 blocks with accurate dimensions, rigid bodies, and colliders.
[VERIFICATION] ALL SELF-VERIFICATION CHECKS PASSED SUCCESSFULLY!
```

### 4-2. DDS 브리지 (가장 중요)

Isaac Sim이 실행 중인 상태에서 WSL2에서:

```bash
source /opt/ros/jazzy/setup.bash
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_DOMAIN_ID=0
export FASTDDS_DEFAULT_PROFILES_FILE=$HOME/fastdds_profile.xml

ros2 topic list
```

기대 결과:
```
/clock
/fr3_1/joint_states   /fr3_1/joint_commands
/fr3_2/joint_states   /fr3_2/joint_commands
/fr3_3/joint_states   /fr3_3/joint_commands
/overhead_camera/rgb  /overhead_camera/depth  /overhead_camera/camera_info
/gemini/custom_goal   /reset_simulation   /tf
```

실제 수신 확인:
```bash
ros2 topic echo /clock --once
ros2 topic hz /fr3_1/joint_states          # 약 100Hz
ros2 topic hz /overhead_camera/rgb         # 약 2Hz
```

TF 트리 확인 (프레임 이름이 로봇마다 다릅니다):
```bash
ros2 topic echo /tf tf2_msgs/msg/TFMessage --once | grep child_frame_id
```
`fr3_link0` / `FR3_2_fr3_link0` / `FR3_3_fr3_link0` / `Block1`~`Block9`가 나와야 합니다.

### 4-3. 노드와 서비스

```bash
ros2 node list --no-daemon
ros2 service list --no-daemon | grep gemini
```
기대: `/gemini/plan_task`, `/gemini/detect_objects`, `/gemini/describe_scene`

### 4-4. 웹 계층

```powershell
Test-NetConnection -ComputerName localhost -Port 9090   # rosbridge
```

---

## 5. 문제 해결

### `ros2 topic list`가 비어 있는데 `ros2 topic hz`는 데이터가 나온다

**디스커버리 문제이지 통신 문제가 아닙니다.** FastDDS 프로파일의 피어 목록을 확인하세요.

```bash
grep address ~/fastdds_profile.xml
```
Windows IP, WSL IP, `127.0.0.1`, `239.255.0.1`이 모두 있어야 합니다.
없다면 `scripts/setup_fastdds_wsl.py`가 구버전입니다 ([SETUP_FIXES.md](SETUP_FIXES.md) 2번 항목).

임시로 타입을 명시하면 디스커버리 없이 데이터를 볼 수 있습니다:
```bash
ros2 topic echo /fr3_1/joint_states sensor_msgs/msg/JointState --once
```

### 재부팅 후 통신이 끊겼다

**WSL2 IP는 재부팅마다 바뀝니다.** 프로파일을 다시 생성하세요.

```powershell
cd scripts
D:\isaacsim61\python.bat setup_fastdds_wsl.py
```

### Isaac Sim이 크래시한다

1. `nvidia-smi`로 드라이버가 580.88 이상인지 확인
2. Isaac Sim이 **6.x**인지 확인 (5.1은 최신 드라이버에서 크래시)
3. 크래시 스택 확인: `D:\isaacsim61\kit\data\Kit\Isaac-Sim Python\6.1\crash_*.txt`
4. Python 측 위치는 같은 폴더의 `*.py.txt` (py-spy 덤프)

### `setup_all.sh --phase 3`이 조용히 끝난다

로그가 `Phase 3.7`에서 끊겼는지 확인하세요.
`set -u`와 ROS setup.bash 충돌입니다 ([SETUP_FIXES.md](SETUP_FIXES.md) 1번 항목).
수정된 스크립트로 다시 실행하면 됩니다. 이미 설치된 패키지는 건너뛰므로 빠릅니다.

### Gemini가 503 UNAVAILABLE을 반환한다

```
Streaming error: 503 UNAVAILABLE. {'error': {'code': 503,
  'message': 'This model is currently experiencing high demand...'}}
```

**Google 측 일시적 용량 문제이며 우리 설정 문제가 아닙니다.** 노드가 자동 재시도합니다.
반복되면 `private/.env`의 `PLANNER_MODEL`을 다른 모델로 바꿔보세요.

### API 키를 못 읽는다

```bash
python3 -c "
import importlib.util
s = importlib.util.spec_from_file_location('gc','wsl_ws/src/isaac_ros2_control/isaac_ros2_control/gemini_config.py')
m = importlib.util.module_from_spec(s); s.loader.exec_module(m)
k = m.get_api_key(); print('OK' if k else 'FAILED', len(k))
"
```
실패하면 `private/.env`의 BOM과 자리표시자 값을 확인하세요.

### 웹 대시보드의 Start/Build 버튼이 동작하지 않는다

`server.cjs`가 WSL 경로를 모릅니다. 서버 실행 전에 설정하세요.
```powershell
$env:WSL_WS = "/home/<사용자명>/catkin_ws"
$env:WSL_DISTRO = "Ubuntu-24.04"
```

---

## 6. 포트와 환경변수

| 포트 | 용도 |
|---|---|
| 5173 | Vite 개발 서버 (웹 UI) |
| 3001 | Express 백엔드 |
| 9090 | rosbridge WebSocket |
| UDP 7400-7500 | DDS 디스커버리 및 데이터 |

| 환경변수 | 값 | 설정 위치 |
|---|---|---|
| `ISAAC_SIM_PATH` | `D:\isaacsim61` | Windows 사용자 환경변수 |
| `ROS_DOMAIN_ID` | `0` | `~/.bashrc`, `launcher.bat` |
| `RMW_IMPLEMENTATION` | `rmw_fastrtps_cpp` | 양쪽 모두 |
| `FASTDDS_DEFAULT_PROFILES_FILE` | `~/fastdds_profile.xml` / `%USERPROFILE%\fastdds_profile.xml` | 양쪽 모두 |
| `ISAAC_RENDERER` | `RaytracedLighting` (기본) | 선택 |
| `GEMINI_ROBOTICS_ENV` | `.env` 경로 명시 | 선택 |
| `WSL_WS` / `WSL_DISTRO` / `ROS_SETUP` | 대시보드 백엔드용 | 선택 |

---

## 7. 알려진 제약

- **WSL2 IP 변동** — 재부팅마다 `setup_fastdds_wsl.py` 재실행이 필요합니다.
- **`app.close()` 종료 크래시** — Isaac Sim 종료 시 크래시 리포터가 뜨는 경우가 있습니다.
  시뮬레이션 동작 자체에는 영향이 없습니다.
- **모델 가용성** — `.env.example`의 `gemini-3.7-flash` / `gemini-robotics-er-2-preview`는
  API 키 권한과 지역에 따라 접근이 제한될 수 있습니다.
- **VRAM 12GB** — 이 데모 규모에서는 충분하지만, 씬을 키우거나 `RealTimePathTracing`을 쓰면 부족할 수 있습니다.
