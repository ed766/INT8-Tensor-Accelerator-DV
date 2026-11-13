"""Sensitivity tests for correlated windows; no RTL-execution claim."""
import unittest
from report_gap_evidence import contributions


def event(kind, cycle, **fields):
    return dict(kind=kind,epoch="0",cycle=str(cycle),eid=str(cycle),**fields)


class GapEvidence(unittest.TestCase):
    def test_maintenance_pairs_actual_start_and_result(self):
        start=event("MAINT_START",1,cmd="0",cache_enabled="1")
        done=event("MAINT_DONE",2,cmd="0",error="1")
        hits=list(contributions([start,done]))
        self.assertEqual(hits[0][:2],('cache_maintenance',('free',0,'error')))
        self.assertFalse(list(contributions([done])))
        self.assertFalse(list(contributions([start,event('RESET_ASSERT',2),done])))

    def test_device_owned_maintenance_cannot_credit_free_window(self):
        parsed=[event('SUBMIT',1,tag='7'),event('MAINT_START',2,cmd='1',cache_enabled='1'),
                event('MAINT_DONE',3,cmd='1',error='0')]
        self.assertEqual(list(contributions(parsed))[0][1],('device',1,'success'))

    def test_repeated_failure_is_same_descriptor_recovery(self):
        fields=dict(tag='7',asid='1',input_iova='80001000',output_iova='80004000',
                    k='4',batch='3',bank='0',generation='1')
        parsed=[event('SUBMIT',1,**fields),event('COMPLETE',2,tag='7',status='5',vectors_done='0'),
                event('SUBMIT',3,**fields),event('COMPLETE',4,tag='7',status='5',vectors_done='1'),
                event('TLB_INVALIDATE',5,all='1'),event('SUBMIT',6,**fields),
                event('COMPLETE',7,tag='7',status='0',vectors_done='3')]
        attempts=[values for family,values,window in contributions(parsed) if family=='retry_attempt']
        self.assertEqual(attempts,[(5,'first'),(5,'repeated')])
        parsed[5]['input_iova']='80009000'
        self.assertFalse(list(contributions(parsed)))

    def test_reset_cannot_join_old_failure_to_new_retry(self):
        fields=dict(tag='7',asid='1',input_iova='80001000',output_iova='80004000',
                    k='4',batch='1',bank='0',generation='1')
        parsed=[event('SUBMIT',1,**fields),event('COMPLETE',2,tag='7',status='2',vectors_done='0'),
                event('RESET_ASSERT',3),event('TLB_INVALIDATE',4,all='1'),
                event('SUBMIT',5,**fields),event('COMPLETE',6,tag='7',status='0',vectors_done='1')]
        self.assertFalse(list(contributions(parsed)))

    def test_irq_credit_requires_actual_nontrapping_m_retirement(self):
        retired=event('RETIRE',1,insn='02004033',trap='0',mstatus='00001808',irq_level='1',irq_timer_level='0')
        self.assertEqual(list(contributions([retired]))[0][1],('external','enabled'))
        retired['trap']='1'
        self.assertFalse(list(contributions([retired])))
        retired.update(trap='0',insn='00000013')
        self.assertFalse(list(contributions([retired])))


if __name__=='__main__':unittest.main()
