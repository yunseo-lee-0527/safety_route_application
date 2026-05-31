"""
전체 데이터 파이프라인 실행

모든 원본 데이터를 GeoJSON으로 변환합니다.
- 학교 정문
- 사고 데이터
- 학교구역 폴리곤
- 통학구역 폴리곤
- 주거 건물
- 최적 경로 (느림 - 12K+ Dijkstra)
- 통학 인원 추정

Usage:
    python scripts/build_all.py
"""

import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from pathlib import Path
import logging
from datetime import datetime

# 현재 디렉토리를 path에 추가
sys.path.append(str(Path(__file__).parent))

# Processor import
from processors.gate_processor import GateProcessor
from processors.accident_processor import AccidentProcessor
from processors.schoolzone_processor import SchoolZoneProcessor
from processors.commuting_zone_processor import CommutingZoneProcessor
from processors.walking_network_processor import WalkingNetworkProcessor
from processors.optimal_path_processor import OptimalPathProcessor
from processors.commute_estimation_processor import CommuteEstimationProcessor

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def main():
    """전체 파이프라인 실행"""
    import argparse
    parser = argparse.ArgumentParser(description='Seoul SchoolZone pipeline')
    parser.add_argument('--force', '-f', action='store_true',
                        help='Re-run all processors even if output already exists')
    args, _ = parser.parse_known_args()

    start_time = datetime.now()
    
    print("\n" + "="*70)
    print("🚀 Yongsan SchoolZone Data Pipeline")
    print("="*70)
    print(f"Started at: {start_time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    # Processor 리스트 (실행 순서 중요 - 의존성 있음)
    processors = [
        ("School Gates",                 GateProcessor()),
        ("Traffic Accidents",            AccidentProcessor()),
        ("School Zones",                 SchoolZoneProcessor()),
        ("Commuting Zones & Buildings",  CommutingZoneProcessor()),
        ("Walking Network",              WalkingNetworkProcessor()),
        # OptimalPathProcessor는 CommutingZoneProcessor 결과에 의존
        # 12K+ 경로 Dijkstra 계산으로 수 분 소요
        ("Optimal Paths (slow)",         OptimalPathProcessor()),
        # CommuteEstimationProcessor는 OptimalPathProcessor 결과에 의존
        ("Commute Estimation",           CommuteEstimationProcessor()),
    ]
    
    results = []
    failed = []
    
    # 각 Processor 실행
    for name, processor in processors:
        print("\n" + "-"*70)
        print(f"📍 Processing: {name}")
        print("-"*70)

        # Level-1 skip: if primary output exists and --force not set
        if not args.force:
            primary_output = (
                getattr(processor, "output_geojson", None)
                or getattr(processor, "zones_geojson", None)
            )
            if primary_output and Path(primary_output).exists():
                print(f"  Skipping -- output exists: {Path(primary_output).name}")
                print("  (Use --force / -f to re-run)")
                results.append(f"SKIPPED {name}")
                continue


        
        try:
            processor.run()
            results.append(f"✅ {name}")
            print(f"✅ {name} completed")
            
        except Exception as e:
            results.append(f"❌ {name}")
            failed.append((name, e))
            logger.error(f"❌ {name} failed: {e}")
            
            # 에러 상세 출력
            import traceback
            traceback.print_exc()
            print(f"\n⚠️  {name} failed but continuing with next processor...\n")
    
    # 최종 결과 출력
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()
    
    print("\n" + "="*70)
    print("📊 Pipeline Results")
    print("="*70)
    
    for result in results:
        print(result)
    
    print(f"\n⏱️  Total time: {duration:.2f} seconds")
    
    # 실패한 작업이 있으면 경고
    if failed:
        print("\n" + "="*70)
        print("⚠️  Some processors failed:")
        print("="*70)
        for name, error in failed:
            print(f"  • {name}: {error}")
        print("\nPlease check the error messages above and fix the issues.")
        print("="*70)
        return 1
    else:
        print("\n" + "="*70)
        print("🎉 All processors completed successfully!")
        print("="*70)
        print("\n📁 Output files location:")
        print("   data/processed/")
        print("\nYou can now run the web application:")
        print("   cd web")
        print("   python -m http.server 8000")
        print("="*70 + "\n")
        return 0


if __name__ == '__main__':
    exit_code = main()
    sys.exit(exit_code)