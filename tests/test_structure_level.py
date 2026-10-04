"""A sustained loud section must not be called quiet because novelty is low."""
import numpy as np
import pytest

import beatscope.structure as structure
from beatscope.structure_features import BarSpan, StructureFeatures


def test_waveform_level_and_legacy_novelty_remain_separate(monkeypatch):
    sr=1000
    audio=np.r_[np.full(2000,.8),np.full(2000,.08)].astype(np.float32)
    spans=[BarSpan(1,0,2,0,2),BarSpan(2,2,4,2,4)]
    monkeypatch.setattr(structure,'extract_structure_features',lambda *a,**k:StructureFeatures(spans,{},{}))
    captured={}
    def infer(features,duration,bars,level,density):
        captured['level']=level.copy()
        return {'segments':[{'start_bar':1,'end_bar':1,'start_time':0,'end_time':2},
                            {'start_bar':2,'end_bar':2,'start_time':2,'end_time':4}], 'diagnostics':{}}
    monkeypatch.setattr(structure,'analyze_structure_segments',infer)
    # Deliberately opposite the waveform amplitude: new spectral events are
    # not evidence for how much sustained acoustic signal is present.
    energy={'fps':1,'start':0,'bands':{'all':[.01,.01,1.,1.]}}
    result=structure.analyze_multiview_structure(audio,sr,[],[],energy,4,2)
    assert captured['level']==pytest.approx([.8,.08])
    assert [s['mean_rms'] for s in result['segments']]==pytest.approx([.8,.08])
    assert [s['mean_energy'] for s in result['segments']]==pytest.approx([.01,1.])
    assert result['diagnostics']['break_level_source']=='per-bar-waveform-rms'


def test_rms_covers_prefix_and_tail_and_sanitizes_nonfinite(monkeypatch):
    audio=np.array([1.,1.,0.,0.,0.,0.,float('nan'),float('inf')])
    spans=[BarSpan(1,1,3,1,3)]
    monkeypatch.setattr(structure,'extract_structure_features',lambda *a,**k:StructureFeatures(spans,{},{}))
    monkeypatch.setattr(structure,'analyze_structure_segments',lambda *a,**k:{
        'segments':[{'start_bar':1,'end_bar':2,'start_time':0,'end_time':4}], 'diagnostics':{}})
    result=structure.analyze_multiview_structure(audio,2,[],[],{},4,2)
    assert result['segments'][0]['mean_rms']==pytest.approx(.5)
