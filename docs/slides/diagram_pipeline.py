#!/usr/bin/env python3
"""
Architecture diagram for the Run1A CE sensitivity pipeline.
Shows the data flow from BO knobs through Geant4 stages, post-processing,
and back to the BO loop.
"""

from graphviz import Digraph


def pipeline_diagram():
    dot = Digraph('ce_pipeline')
    dot.attr(
        rankdir='TB',
        bgcolor='white',
        pad='0.25',
        nodesep='0.30',
        ranksep='0.40',
        dpi='300',
    )

    # palette
    BLUE_DEEP    = '#1565C0'   # BO / orchestration
    BLUE_LIGHT   = '#90CAF9'   # data files
    GREEN_DEEP   = '#2E7D32'   # Geant4 stage (expensive)
    GREEN_LIGHT  = '#A5D6A7'   # analysis stage (cheap)
    ORANGE       = '#EF6C00'   # external/analytic inputs
    RED          = '#C62828'   # the metric / output
    PURPLE       = '#6A1B9A'   # constants / hardcoded

    dot.node_attr.update(fontname='Helvetica', fontsize='13',
                         margin='0.16,0.10')
    dot.edge_attr.update(fontname='Helvetica', fontsize='11')

    # =========================================================
    # Legend
    # =========================================================
    legend = '''<<TABLE BORDER="1" CELLBORDER="0" CELLSPACING="3" CELLPADDING="4" COLOR="#CCCCCC">
        <TR>
            <TD BGCOLOR="#1565C0"><FONT COLOR="white" POINT-SIZE="11"> autoresearch driver </FONT></TD>
            <TD BGCOLOR="#2E7D32"><FONT COLOR="white" POINT-SIZE="11"> Geant4 stage </FONT></TD>
            <TD BGCOLOR="#A5D6A7"><FONT POINT-SIZE="11"> Analysis stage </FONT></TD>
            <TD BGCOLOR="#90CAF9"><FONT POINT-SIZE="11"> Data file </FONT></TD>
            <TD BGCOLOR="#EF6C00"><FONT COLOR="white" POINT-SIZE="11"> Analytic input </FONT></TD>
            <TD BGCOLOR="#C62828"><FONT COLOR="white" POINT-SIZE="11"> Metric </FONT></TD>
        </TR>
    </TABLE>>'''
    dot.node('legend', legend, shape='none')

    # =========================================================
    # ROW 1: autoresearch driver cluster (proposer + leaderboard)
    # =========================================================
    YELLOW = '#FFC107'   # external LLM API (separate color for non-driver)

    with dot.subgraph(name='cluster_autoresearch') as c:
        c.attr(label='autoresearch driver  (autoresearch_loop.py / autoresearch_bo.py)',
               labelloc='t', fontsize='13', fontname='Helvetica-Bold',
               style='rounded,dashed', color=BLUE_DEEP, penwidth='2',
               margin='12')

        c.node('leaderboard', 'leaderboard.tsv\n(persistent history\nof past evaluations)',
               shape='cylinder', style='filled',
               fillcolor=BLUE_LIGHT, penwidth='0',
               fontsize='11')

        # Phase 1: LLM proposer
        c.node('llm_proposer',
               'LLM proposer\nClaude Opus 4.7\nPhase 1 (1D thickness scan)',
               shape='box', style='rounded,filled',
               fillcolor=BLUE_DEEP, fontcolor='white', penwidth='0',
               fontsize='12')

        # Phase 2: BO proposer
        c.node('bo_proposer',
               'GP + EI proposer\n(skopt)\nPhase 2 (7D BO scan)',
               shape='box', style='rounded,filled',
               fillcolor=BLUE_DEEP, fontcolor='white', penwidth='0',
               fontsize='12')

    # External LLM API (lives outside the driver)
    dot.node('litellm',
             'LiteLLM proxy\nlitellm.fnal.gov/v1\n(Azure-hosted Claude)',
             shape='box3d', style='filled',
             fillcolor=YELLOW, penwidth='0',
             fontsize='11')

    # Knobs (output of the proposer)
    dot.node('knobs', 'Geometry knobs\n(halfT, nFoils, deltaZ,\nz0, R_start/mid/end)',
             shape='note', style='filled',
             fillcolor=BLUE_LIGHT, penwidth='0')

    # =========================================================
    # ROW 2: Stage 1 - mubeam G4
    # =========================================================
    dot.node('beam', 'MuBeamCat.Run1Baa\n(pre-generated mu- beam)',
             shape='cylinder', style='filled', fillcolor=BLUE_LIGHT, penwidth='0')
    dot.node('mubeam', 'STAGE 1: run1a_mubeam\nGeant4 mu- through DS\n(30 jobs, ~4 min)',
             shape='box', style='rounded,filled',
             fillcolor=GREEN_DEEP, fontcolor='white', penwidth='0',
             fontsize='13')

    # =========================================================
    # ROW 3a: per-job TargetStops .art files (30 of them)
    # =========================================================
    dot.node('tgtstops', 'TargetStops.Run1A.*.art\n(30 per-job files,\nmu- stop pos+time)',
             shape='cylinder', style='filled', fillcolor=BLUE_LIGHT, penwidth='0',
             fontsize='11')

    # =========================================================
    # ROW 3b: mu_stops_job concat step (separate, sequential)
    # =========================================================
    dot.node('concat', 'mu_stops_job\n(serial concat step,\nart job ~30 sec)',
             shape='box', style='rounded,filled',
             fillcolor=GREEN_LIGHT, penwidth='0',
             fontsize='12')

    # =========================================================
    # ROW 3c: MuminusStopsCat output
    # =========================================================
    dot.node('stops', 'MuminusStopsCat.Run1A.art\n(single concatenated catalog\nof all mu- stops)',
             shape='cylinder', style='filled', fillcolor=BLUE_LIGHT, penwidth='0',
             fontsize='11')

    # =========================================================
    # ROW 4: Stage 2 - mustops G4 (3 modes)
    # =========================================================
    dot.node('mustops', 'STAGE 2: run1a_mustops\nResample stop -> generator\n-> G4 propagate to tracker/calo\n(30 jobs x 3 modes, ~15 min)',
             shape='box', style='rounded,filled',
             fillcolor=GREEN_DEEP, fontcolor='white', penwidth='0',
             fontsize='13')

    # =========================================================
    # ROW 5: CE art outputs (3 modes)
    # =========================================================
    dot.node('ce',     'dts.*.CeEndpoint\n(ce mode: e- @ 104.97 MeV/c)',
             shape='cylinder', style='filled', fillcolor=BLUE_LIGHT, penwidth='0',
             fontsize='11')
    dot.node('fgamma', 'dts.*.FlatGamma\n(flat photon spectrum)',
             shape='cylinder', style='filled', fillcolor=BLUE_LIGHT, penwidth='0',
             fontsize='11')
    dot.node('felec',  'dts.*.FlatElectron\n(flat e- spectrum)',
             shape='cylinder', style='filled', fillcolor=BLUE_LIGHT, penwidth='0',
             fontsize='11')

    # =========================================================
    # ROW 6: Stage 3 - EdepAna
    # =========================================================
    dot.node('edep', 'STAGE 3: edep_analysis\nEdepAna analyzer:\ntrk_front_E, dE, calo Edep',
             shape='box', style='rounded,filled',
             fillcolor=GREEN_LIGHT, penwidth='0',
             fontsize='13')

    # histograms file
    dot.node('hists', 'nts.owner.edep.*.root\n(signal hist + response func)',
             shape='cylinder', style='filled', fillcolor=BLUE_LIGHT, penwidth='0')

    # =========================================================
    # ROW 7: external analytic inputs
    # =========================================================
    dot.node('dio', 'DIO spectrum\n(Heeck-Szafron, analytic)',
             shape='note', style='filled',
             fillcolor=ORANGE, fontcolor='white', penwidth='0',
             fontsize='11')
    dot.node('cosmic', 'Cosmic rate\n(hardcoded:\n1.8e-3 ev/s/MeV/c)',
             shape='note', style='filled',
             fillcolor=PURPLE, fontcolor='white', penwidth='0',
             fontsize='11')
    dot.node('resol', 'Tracker resol.\n(Gaussian sigma=0.2 MeV)',
             shape='note', style='filled',
             fillcolor=PURPLE, fontcolor='white', penwidth='0',
             fontsize='11')
    dot.node('norm', 'Normalization\nN_POT=1e18\nR_mue=1e-9\nBR_cap=0.609',
             shape='note', style='filled',
             fillcolor=PURPLE, fontcolor='white', penwidth='0',
             fontsize='11')

    # =========================================================
    # ROW 8: Stage 4 - sensitivity macro
    # =========================================================
    dot.node('sens', 'STAGE 4: rough_run1a_sensitivity.C\nconvolve(sig, dio) with response;\nadd cosmic; scan windows for max S/sqrt(B)',
             shape='box', style='rounded,filled',
             fillcolor=GREEN_LIGHT, penwidth='0',
             fontsize='13')

    # =========================================================
    # ROW 9: metric
    # =========================================================
    dot.node('metric', 'S / sqrt(B)\n+ optimal momentum window',
             shape='box', style='rounded,filled',
             fillcolor=RED, fontcolor='white', penwidth='0',
             fontsize='14')

    # =========================================================
    # EDGES: main vertical flow
    # =========================================================

    # Inside the autoresearch driver: leaderboard <-> proposers
    dot.edge('leaderboard', 'llm_proposer',
             label='history',
             color=BLUE_DEEP, penwidth='1.5', arrowhead='vee', fontsize='10')
    dot.edge('leaderboard', 'bo_proposer',
             label='history',
             color=BLUE_DEEP, penwidth='1.5', arrowhead='vee', fontsize='10')

    # LLM proposer talks to LiteLLM external API
    dot.edge('llm_proposer', 'litellm',
             label='OpenAI-compatible /v1/chat',
             style='dashed', color=BLUE_DEEP, penwidth='1.2',
             arrowhead='vee', dir='both', fontsize='10', constraint='false')

    # Both proposers emit geometry knobs
    dot.edge('llm_proposer', 'knobs',
             label='ask (Phase 1)',
             color=BLUE_DEEP, penwidth='1.5', arrowhead='vee', fontsize='10')
    dot.edge('bo_proposer', 'knobs',
             label='ask (Phase 2)',
             color=BLUE_DEEP, penwidth='2', arrowhead='vee', fontsize='10')

    dot.edge('knobs', 'mubeam', label='geom.txt', color=BLUE_DEEP, penwidth='1.5')
    dot.edge('beam',  'mubeam', label='input', color=GREEN_DEEP, penwidth='1.5')
    dot.edge('mubeam', 'tgtstops', label='per-job output (x30)',
             color=GREEN_DEEP, penwidth='1.5')
    dot.edge('tgtstops', 'concat', label='all 30 files',
             color=GREEN_LIGHT, penwidth='1.5')
    dot.edge('concat', 'stops',
             color=GREEN_LIGHT, penwidth='1.5')
    dot.edge('stops', 'mustops', label='resampler input',
             color=GREEN_DEEP, penwidth='1.5')
    dot.edge('knobs', 'mustops', label='geom.txt',
             color=BLUE_DEEP, penwidth='1.5', style='dashed', constraint='false')

    # mustops splits to 3 modes
    dot.edge('mustops', 'ce',     color=GREEN_DEEP, penwidth='1.5')
    dot.edge('mustops', 'fgamma', color=GREEN_DEEP, penwidth='1.2', style='dashed')
    dot.edge('mustops', 'felec',  color=GREEN_DEEP, penwidth='1.2', style='dashed')

    # 3 modes -> edep
    dot.edge('ce',     'edep', color=GREEN_LIGHT, penwidth='1.5')
    dot.edge('fgamma', 'edep', color=GREEN_LIGHT, penwidth='1.2', style='dashed')
    dot.edge('felec',  'edep', color=GREEN_LIGHT, penwidth='1.2', style='dashed')

    # edep -> hists
    dot.edge('edep', 'hists', color=GREEN_LIGHT, penwidth='1.5')

    # hists + analytic inputs -> sens
    dot.edge('hists', 'sens', label='signal hist + response',
             color=GREEN_LIGHT, penwidth='2')
    dot.edge('dio',    'sens', color=ORANGE, penwidth='1.5')
    dot.edge('cosmic', 'sens', color=PURPLE, penwidth='1.5')
    dot.edge('resol',  'sens', color=PURPLE, penwidth='1.5')
    dot.edge('norm',   'sens', color=PURPLE, penwidth='1.5')

    # sens -> metric
    dot.edge('sens', 'metric', color=RED, penwidth='2.5', arrowhead='vee')

    # closing the loop: metric -> leaderboard (which feeds the proposer next iter)
    dot.edge('metric', 'leaderboard',
             label='append (cfg, knobs, S/sqrt(B))',
             color=BLUE_DEEP, penwidth='2.5', arrowhead='vee',
             style='dashed', constraint='false', fontsize='10')

    # group analytic inputs at the same rank (next to sens)
    with dot.subgraph() as r:
        r.attr(rank='same')
        r.node('dio'); r.node('cosmic'); r.node('resol'); r.node('norm')
        r.node('sens')

    # group 3 mode files at same rank
    with dot.subgraph() as r:
        r.attr(rank='same')
        r.node('ce'); r.node('fgamma'); r.node('felec')

    # legend, MuBeamCat at top
    with dot.subgraph() as r:
        r.attr(rank='same')
        r.node('legend'); r.node('beam')

    return dot


if __name__ == '__main__':
    d = pipeline_diagram()
    d.render('pipeline_diagram', format='png', cleanup=True)
    print('wrote pipeline_diagram.png')
