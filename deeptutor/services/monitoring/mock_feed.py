import time
import asyncio
import dataclasses
from typing import Dict, Any, AsyncGenerator
from deeptutor.services.monitoring.cv_pipeline import get_cv_pipeline

class MockVideoFeed:
    """Synthetic frame generator for --mock-camera dev mode.
    
    Generates test scenarios:
    - 'present': Simulated face at center, good posture
    - 'absent': No face detected
    - 'distracted': Face looking away
    - 'phone': Phone-like object detected
    - 'cycle': Cycles through all scenarios
    """
    
    def __init__(self, scenario: str = 'cycle', fps: int = 5):
        self.scenario = scenario
        self.fps = fps
        self._scenarios = ['present', 'distracted', 'phone', 'absent']
        self._scenario_idx = 0
        self._last_scenario_switch = time.time()
        self.pipeline = get_cv_pipeline()
    
    def _get_current_scenario(self) -> str:
        if self.scenario != 'cycle':
            return self.scenario
            
        now = time.time()
        # Switch scenario every 10 seconds in cycle mode
        if now - self._last_scenario_switch > 10.0:
            self._scenario_idx = (self._scenario_idx + 1) % len(self._scenarios)
            self._last_scenario_switch = now
            
        return self._scenarios[self._scenario_idx]
        
    def _map_scenario_to_pipeline_scenario(self, internal_scenario: str) -> str:
        mapping = {
            'present': 'normal_study',
            'absent': 'absent',
            'distracted': 'looking_away',
            'phone': 'phone_usage'
        }
        return mapping.get(internal_scenario, 'normal_study')

    def get_mock_frame_analysis(self) -> Dict[str, Any]:
        """Returns a mock FrameAnalysisResult-like dict."""
        current = self._get_current_scenario()
        pipeline_scenario = self._map_scenario_to_pipeline_scenario(current)
        
        telemetry = self.pipeline.generate_mock_telemetry(scenario=pipeline_scenario)
        result = self.pipeline.analyze_payload(telemetry)
        
        return dataclasses.asdict(result)

    async def stream_mock_frames(self, session_id: str, duration_seconds: int = 300):
        """Async generator yielding mock analysis results at the configured FPS."""
        start_time = time.time()
        sleep_duration = 1.0 / self.fps
        
        while (time.time() - start_time) < duration_seconds:
            result = self.get_mock_frame_analysis()
            result['session_id'] = session_id
            yield result
            await asyncio.sleep(sleep_duration)
