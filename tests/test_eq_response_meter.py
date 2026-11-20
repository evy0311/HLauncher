"""Low-level graph tails must not become the spectral measurement origin."""
from pathlib import Path
import sys
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from check_eq_response import spectrum,RATE


class SpectrumWindow(unittest.TestCase):
    def test_quiet_tail_then_gap_then_signal_measures_steady_amplitudes(self):
        t=np.arange(RATE*4)/RATE
        wave=.003*np.sin(2*np.pi*20*t)+.002*np.sin(2*np.pi*1000*t)
        tail=.0002*np.sin(2*np.pi*20*np.arange(RATE//2)/RATE)
        capture=np.concatenate((tail,np.zeros(RATE),wave,np.zeros(RATE//4)))
        pcm=np.column_stack((capture,capture*.7))
        actual=spectrum(pcm,[20,1000])
        np.testing.assert_allclose(actual,[[.003,.0021],[.002,.0014]],atol=1e-8)

    def test_silence_and_short_captures_are_not_valid_measurements(self):
        for signal in (np.zeros((RATE*4,2)),np.ones((RATE,2))*.003):
            with self.assertRaises(RuntimeError):spectrum(signal,[20])
