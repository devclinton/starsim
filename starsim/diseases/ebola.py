"""
Define Ebola model.
Adapted from https://github.com/optimamodel/gavi-outbreaks/blob/main/stisim/gavi/ebola.py
Original version by@domdelport and @RomeshA
"""

import numpy as np
import starsim as ss
from starsim.diseases.sir import SIR

__all__ = ['Ebola']


class Ebola(SIR):

    def __init__(self, pars=None, par_dists=None, *args, **kwargs):
        """ Initialize with parameters """

        pars = ss.dictmergeleft(pars,
            # Natural history parameters, all specified in days
            dur_exp2symp = 12.7, # Add source
            dur_symp2sev =    6, # Add source
            dur_sev2dead =  1.5, # Add source
            dur_dead2buried = 2, # Add source
            dur_symp2rec =   10, # Add source
            dur_sev2rec =  10.4, # Add source
            p_sev =         0.7, # Add source
            p_death =      0.55, # Add source
            p_safe_bury =  0.25, # Probability of a safe burial - should be linked to diagnoses

            # Initial conditions and beta
            init_prev = 0.005,
            beta = None,
            sev_factor = 2.2,
            unburied_factor = 2.1,
        )

        par_dists = ss.dictmergeleft(par_dists,
            dur_exp2symp    = ss.lognorm_ex,
            dur_symp2sev    = ss.lognorm_ex,
            dur_sev2dead    = ss.lognorm_ex,
            dur_dead2buried = ss.lognorm_ex,
            dur_symp2rec    = ss.lognorm_ex,
            dur_sev2rec     = ss.lognorm_ex,
            p_sev           = ss.bernoulli,
            p_death         = ss.bernoulli,
            p_safe_bury     = ss.bernoulli,
            init_prev       = ss.bernoulli,
        )

        super().__init__(pars=pars, par_dists=par_dists, *args, **kwargs)

        # Boolean states
        
        self.add_states(
            # SIR are added automatically, here we add E
            ss.BoolArr('exposed'),
            ss.BoolArr('severe'),
            ss.BoolArr('recovered'),
            ss.BoolArr('buried'),
    
            # Timepoint states
            ss.FloatArr('ti_exposed'),
            ss.FloatArr('ti_severe'),
            ss.FloatArr('ti_recovered'),
            ss.FloatArr('ti_dead'),
            ss.FloatArr('ti_buried'),
        )

        return

    @property
    def infectious(self):
        return self.infected | self.exposed

    def update_pre(self, sim):

        # Progress exposed -> infected
        infected = (self.exposed & (self.ti_infected <= sim.ti)).uids
        self.exposed[infected] = False
        self.infected[infected] = True

        # Progress infectious -> severe
        severe = (self.infected & (self.ti_severe <= sim.ti)).uids
        self.severe[severe] = True

        # Progress infected -> recovered
        recovered = (self.infected & (self.ti_recovered <= sim.ti)).uids
        self.infected[recovered] = False
        self.recovered[recovered] = True

        # Progress severe -> recovered
        recovered_sev = (self.severe & (self.ti_recovered <= sim.ti)).uids
        self.severe[recovered_sev] = False
        self.recovered[recovered_sev] = True

        # Trigger deaths
        deaths = (self.ti_dead <= sim.ti).uids
        if len(deaths):
            sim.people.request_death(deaths)

        # Progress dead -> buried
        buried = (self.ti_buried <= sim.ti).uids
        self.buried[buried] = True
        
        return

    def set_prognoses(self, sim, uids, source_uids=None):
        """ Set prognoses for those who get infected """
        # Do not call set_prognoses on the parent
        #super().set_prognoses(sim, uids, source_uids)

        self.susceptible[uids] = False
        self.exposed[uids] = True
        self.ti_exposed[uids] = sim.ti

        p = self.pars

        # Determine when exposed become infected
        self.ti_infected[uids] = sim.ti + p.dur_exp2symp.rvs(uids) / sim.dt

        # Determine who progresses to sever and when
        sev_uids = p.p_sev.filter(uids)
        self.ti_severe[sev_uids] = self.ti_infected[sev_uids] + p.dur_symp2sev.rvs(sev_uids) / sim.dt

        # Determine who dies and who recovers and when
        dead_uids = p.p_death.filter(sev_uids)
        self.ti_dead[dead_uids] = self.ti_severe[dead_uids] + p.dur_sev2dead.rvs(dead_uids) / sim.dt
        rec_sev_uids = np.setdiff1d(sev_uids, dead_uids)
        self.ti_recovered[rec_sev_uids] = self.ti_severe[rec_sev_uids] + p.dur_sev2rec.rvs(rec_sev_uids) / sim.dt
        rec_symp_uids = np.setdiff1d(uids, sev_uids)
        self.ti_recovered[rec_symp_uids] = self.ti_infected[rec_symp_uids] + p.dur_symp2rec.rvs(rec_symp_uids) / sim.dt

        # Determine time of burial - either immediate (safe burials) or after a delay (unsafe)
        safe_buried = p.p_safe_bury.filter(dead_uids)
        unsafe_buried = np.setdiff1d(dead_uids, safe_buried)
        self.ti_buried[safe_buried] = self.ti_dead[safe_buried]
        self.ti_buried[unsafe_buried] = self.ti_dead[unsafe_buried] + p.dur_dead2buried.rvs(unsafe_buried) / sim.dt

        # Change rel_trans values
        self.rel_trans[self.infectious] = 1
        self.rel_trans[self.severe] = self.pars['sev_factor']  # Change for severe
        unburied_uids = ((self.ti_dead <= sim.ti) & (self.ti_buried > sim.ti)).uids
        self.rel_trans[unburied_uids] = self.pars['unburied_factor']  # Change for unburied

        return

    def update_death(self, sim, uids):
        # Reset infected/recovered flags for dead agents
        for state in ['susceptible', 'exposed', 'infected', 'severe', 'recovered']:
            self.statesdict[state][uids] = False
        return
