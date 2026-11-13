"""Finite directed sequences and reproducible multi-job firmware schedules."""
import random


def cases():
    rows = []
    def add(name, family, code, *, k=64, batch=4, irq=0, cache=0,
            combined=0, stall=0, reset="none", b_delay=0, r_delay=0, extra=()):
        rows.append(dict(name="stateful_" + name, family=family, code=code,
                         stall=stall, b_delay=b_delay, r_delay=r_delay, extra=extra,
                         spec=("stateful_" + name,k,batch,1,8,irq,cache,"","O2",1,
                               9600+len(rows),0,combined,-1,"",reset)))
    add("irq_fault_timer", "irq", 1, k=4,batch=1,irq=1,b_delay=512)
    add("irq_mask_pending", "irq", 2, k=4,batch=1,irq=1,b_delay=9)
    add("irq_wfi_timer", "irq", 3, k=64,batch=1,irq=1,b_delay=512)
    for phase in ("early", "middle", "finalize", "response"):
        add("reset_m_dma_"+phase,"reset",10,reset="m_dma_"+phase,r_delay=64)
    add("tag_wrap", "resources",20,k=4,batch=1)
    add("both_bank_queue", "resources",21,k=4,batch=1,r_delay=64)
    add("tlb_eviction", "translation",30,k=4,batch=1)
    add("permission_hit", "translation",31,k=4,batch=1)
    add("repeated_retry", "translation",32,k=4,batch=1)
    add("cache_dependency", "cache",40,cache=1,r_delay=32)
    add("cache_maint_retry", "cache",41,cache=1,r_delay=16)
    for stall in (0,25,50,75):
        add(f"pressure_{stall}","progress",50,k=4,batch=1,stall=stall,b_delay=8)
    add("sleep_arithmetic", "progress",51,combined=1,k=64,batch=4,
        extra=("TEST_CHIPLET_SLEEP_DURING",))
    for code,label in ((60,"round_ties"),(61,"saturation"),(62,"zero_points_relu"),(63,"accumulator_wrap")):
        add(label,"numerical",code,k=4,batch=1,stall=25,b_delay=8)
    add("csr_edges", "edges",70,k=4,batch=1)
    add("input_permission", "edges",71,k=4,batch=1)
    add("input_bus_error", "edges",72,k=4,batch=1)
    add("invalid_generation", "edges",73,k=4,batch=1)
    add("queue_full_recover", "edges",74,k=64,batch=1,r_delay=1024)
    add("pop_wait", "edges",75,k=4,batch=1,b_delay=16)
    rows[-1]["pop_wait"]=6
    add("last_output_retry", "edges",76,k=4,batch=1,stall=50,b_delay=16)
    add("m_corners_live", "edges",78,r_delay=32)
    add("mailbox_reserved", "edges",77,k=4,batch=1)
    add("lifetime_campaign", "end_to_end",81,k=4,batch=1,stall=25,b_delay=16,r_delay=256)
    add("cross_stage_retry", "end_to_end",82,k=4,batch=1,stall=50,b_delay=16)
    add("handler_cached_arithmetic", "end_to_end",83,k=64,batch=4,cache=1,b_delay=1024)
    add("fault_both_pending", "end_to_end",84,k=4,batch=1,irq=1,b_delay=64)
    add("reset_multiple_owners", "end_to_end",85,k=4,batch=1,irq=1,r_delay=256,b_delay=64,reset="multiple_owners")
    add("queued_invalidation", "end_to_end",86,k=4,batch=1,r_delay=256,b_delay=32)
    add("read_permission_downgrade", "end_to_end",87,k=4,batch=1,stall=25,r_delay=32)
    add("contended_sleep_drain", "end_to_end",88,k=64,batch=4,combined=1,stall=75,r_delay=64,b_delay=64,
        extra=("TEST_CHIPLET_SLEEP_DURING",))
    add("stale_mapping_unowned_page", "gap_ownership",89,k=4,batch=1,cache=1,r_delay=512,b_delay=64)
    for phase in ("metadata_status","metadata_address","metadata_stage","publication","before_pop","ptw_req","accepted_output_write","dma_b_wait","mem_rsp","host_w_wait","maintenance_invalidation"):
        add("epoch_"+phase,"gap_reset",91,k=4,batch=1,cache=int(phase=="maintenance_invalidation"),reset=phase,r_delay=64,b_delay=64)
    for stall in (0,25,50,75):
        add("fabric_contention_"+str(stall),"gap_contention",92,k=64,batch=4,stall=stall,r_delay=8,b_delay=8,
            combined=1,extra=("TEST_FABRIC_CONTENDER","TEST_CHIPLET_SLEEP_DURING"))
    add("cache_alias_dirty_eviction","gap_cache",93,k=4,batch=1,cache=1,r_delay=32,b_delay=32)
    add("retire_reference_pressure","gap_resources",94,k=4,batch=1,r_delay=8,b_delay=8)
    add("permission_hit_independent","gap_translation",95,k=4,batch=1,r_delay=32,b_delay=32)
    add("alias_unowned_line","gap_ownership",96,k=4,batch=1,cache=1,r_delay=512,b_delay=64)
    add("retry_prefix_independent","gap_recovery",98,k=4,batch=1,stall=25,b_delay=32)
    add("retry_input_independent","gap_recovery",99,k=4,batch=1,stall=50,r_delay=32)
    return rows


def ownership_negative_case(name="stateful_stale_mapping_owned_page"):
    if name=="stateful_handler_owned_line":
        row=dict(next(c for c in cases() if c['code']==83))
        row.update(name=name,extra=("TEST_HANDLER_OWNED_LINE",))
        row['spec']=(name,*row['spec'][1:7],"NEG_STALE_OWNERSHIP",*row['spec'][8:])
        return row
    row=dict(next(c for c in cases() if c["code"]==(89 if name=="stateful_stale_mapping_owned_page" else 96)))
    row.update(name=name,code=90 if name=="stateful_stale_mapping_owned_page" else 97)
    row["spec"]=(row["name"],*row["spec"][1:7],"NEG_STALE_OWNERSHIP",*row["spec"][8:])
    return row


def random_cases(count=32):
    rows=[]
    for index in range(count):
        seed=17001+index
        rng=random.Random(seed)
        k=(4,8,16,32,64)[index%5];cache=(index//4)%2
        name=f"stateful_random_{seed}"
        rows.append(dict(name=name,family="random",code=80,stall=(0,25,50,75)[index%4],
                         b_delay=rng.choice((0,8,32)),r_delay=rng.choice((0,16,64)),
                         extra=(f"STATEFUL_RANDOM_SEED={seed}",),
                         spec=(name,k,1,1+index%3,index%16,0,cache,"","O2",1,seed,0,0,-1,"","none")))
    return rows
