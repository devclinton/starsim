"""
Define example disease modules
"""

import numpy as np
import stisim as ss
import sciris as sc
from .disease import Disease

class SIR(Disease):
    """
    Example SIR model

    This class implements a basic SIR model with states for susceptible,
    infected/infectious, and recovered. It also includes deaths, and basic
    results.

    Note that this class is not currently compatible with common random numbers.
    """

    def __init__(self, pars=None, *args, **kwargs):

        default_pars = {
            'dur_inf': ss.weibull(shape=5, scale=1, rng='Duration of SIR Infection'),
            'p_death': 0.2,
            'initial': 3,
            'beta': None,
        }

        super().__init__(pars=ss.omerge(default_pars, pars), *args, **kwargs)

        self.susceptible = ss.State('susceptible', bool, True)
        self.infected = ss.State('infected', bool, False)
        self.recovered = ss.State('recovered', bool, False)

        self.t_infected = ss.State('t_infected', float, np.nan)
        self.t_recovered = ss.State('t_recovered', float, np.nan)
        self.t_dead = ss.State('t_dead', float, np.nan)

        # Define a random number generator for deciding which agents will die
        self.rng_dead = ss.RNG(f'dead_{self.name}')
        return

    def initialize(self, sim):
        super().initialize(sim)
        self.pars['dur_inf'].initialize(sim)
        return

    def init_results(self, sim):
        """
        Initialize results
        """
        super().init_results(sim)
        self.results += ss.Result(self.name, 'prevalence', sim.npts, dtype=float)
        self.results += ss.Result(self.name, 'new_infections', sim.npts, dtype=int)
        return

    def update_pre(self, sim):
        # Progress infectious -> recovered
        recovered = ss.true(self.infected & (self.t_recovered <= sim.year))
        self.infected[recovered] = False
        self.recovered[recovered] = True

        # Trigger deaths
        deaths = ss.true(self.t_dead <= sim.year)
        sim.people.request_death(deaths)
        return len(deaths)

    def update_death(self, sim, uids):
        # Reset infected/recovered flags for dead agents
        # This is an optional step. Implementing this function means that in `SIR.update_results()` the prevalence
        # calculation does not need to filter the infected agents by the alive agents. An alternative would be
        # to omit implementing this function, and instead filter by the alive agents when calculating prevalence
        super().update_death(sim, uids)
        self.infected[uids] = False
        self.recovered[uids] = False
        return

    def validate_pars(self, sim):
        if self.pars.beta is None:
            self.pars.beta = sc.objdict({k: 1 for k in sim.people.networks})
        return

    def set_initial_states(self, sim):
        """
        Set initial values for states. This could involve passing in a full set of initial conditions,
        or using init_prev, or other. Note that this is different to initialization of the State objects
        i.e., creating their dynamic array, linking them to a People instance. That should have already
        taken place by the time this method is called.
        """
        initial_cases = np.random.choice(sim.people.uid, self.pars['initial'], replace=False)
        self.infect(sim, initial_cases)
        return

    def infect(self, sim, uids):
        # Carry out state changes associated with infection
        self.susceptible[uids] = False
        self.infected[uids] = True
        self.t_infected[uids] = sim.year

        # Calculate and schedule future outcomes for recovery/death
        dur_inf = self.pars['dur_inf'].sample(len(uids))
        dead = np.random.random(len(uids)) < self.pars.p_death
        self.t_recovered[uids[~dead]] = sim.year + dur_inf[~dead]
        self.t_dead[uids[dead]] = sim.year + dur_inf[dead]

        # Update result count of new infections - important to use += because infect() may be called multiple times
        # per timestep
        self.results['new_infections'][sim.ti] += len(uids)
        return

    def make_new_cases(self, sim): # DJK TODO: Why not use the base class here?
        for k, layer in sim.people.networks.items():
            if k in self.pars['beta']:
                rel_trans = (self.infected & sim.people.alive).astype(float)
                rel_sus = (self.susceptible & sim.people.alive).astype(float)
                for a, b, beta in [[layer.contacts['p1'], layer.contacts['p2'], self.pars['beta'][k]],
                                   [layer.contacts['p2'], layer.contacts['p1'], self.pars['beta'][k]]]:
                    # probability of a->b transmission
                    p_transmit = rel_trans[a] * rel_sus[b] * layer.contacts['beta'] * beta * sim.dt
                    new_cases = np.random.random(len(a)) < p_transmit
                    if new_cases.any():
                        self.infect(sim, b[new_cases])
        return

    def update_results(self, sim):
        super().update_results(sim)
        self.results['prevalence'][sim.ti] = self.results.n_infected[sim.ti] / np.count_nonzero(sim.people.alive)
        return

class NCD(Disease):
    """
    Example non-communicable disease

    This class implements a basic NCD model with risk of developing a condition
    (e.g., hypertension, diabetes), a state for having the condition, and associated
    mortality.
    """
    def __init__(self, pars=None):
        default_pars = {
            'initial': ss.bernoulli(0.3, rng='NCD initial prevalence'), # Initial prevalence of risk factors
            #'p_affected_given_risk': 0.1, # 10% chance per year of acquiring
            'affection_rate': ss.rate(0.1, rng='Acquisition rate amongst those at risk'), # 10% chance per year of acquiring
            'prognosis': ss.weibull(2, 5, rng='Time in years between first becoming affected and death'),
        }

        ss.Module.__init__(self, ss.omerge(default_pars, pars))
        self.at_risk  = ss.State('at_risk', bool, False)
        self.affected = ss.State('affected', bool, False)
        self.ti_dead  = ss.State('ti_dead', int, ss.INT_NAN)

        #self.rng_initial  = ss.RNG(f'initial_{self.name}')
        #self.d_init_cases  = ss.bernoulli_filter(self.pars['risk_prev'], rng=f'initial_{self.name}')
        #self.rng_affected  = ss.RNG(f'affected_{self.name}')
        #self.rng_dead     = ss.RNG(f'dead_{self.name}')
        return

    @property
    def not_at_risk(self):
        return ~self.at_risk

    def initialize(self, sim):
        super().initialize(sim)
        print('DJK TODO MODULE INIT OF DISTRIBS')
        self.pars['initial'].initialize(sim)
        self.pars['affection_rate'].initialize(sim)
        self.pars['prognosis'].initialize(sim)
        #self.d_dead = ss.bernoulli_filter(sim.dt*self.pars['p_death_given_risk'], rng=f'dead_{self.name}').initialize(sim)
        return

    def set_initial_states(self, sim):
        """
        Set initial values for states. This could involve passing in a full set of initial conditions,
        or using init_prev, or other. Note that this is different to initialization of the State objects
        i.e., creating their dynamic array, linking them to a People instance. That should have already
        taken place by the time this method is called.
        """
        initial_cases = self.pars['initial'].filter(ss.true(sim.people.alive))
        self.at_risk[initial_cases] = True
        return initial_cases

    def update_pre(self, sim):
        #deaths = self.rng_dead.bernoulli_filter(sim.dt*self.pars['p_death_given_risk'], ss.true(self.affected))
        deaths = ss.true(self.ti_dead == sim.ti)
        sim.people.request_death(deaths)
        #self.ti_dead[deaths] = sim.ti
        return

    def make_new_cases(self, sim):
        new_cases = self.pars['affection_rate'].filter(ss.true(self.at_risk))
        #new_cases = self.rng_affected.bernoulli_filter(self.pars['p_affected_given_risk'], ss.true(self.at_risk))
        self.affected[new_cases] = True
        self.ti_dead[new_cases] = sim.ti + sc.randround(self.pars['prognosis'].sample(new_cases) / sim.dt)
        return new_cases

    def init_results(self, sim):
        """
        Initialize results
        """
        super().init_results(sim)
        self.results += ss.Result(self.name, 'n_not_at_risk', sim.npts, dtype=int)
        self.results += ss.Result(self.name, 'prevalence', sim.npts, dtype=float)
        self.results += ss.Result(self.name, 'new_deaths', sim.npts, dtype=int)
        return

    def update_results(self, sim):
        super().update_results(sim)
        self.results['n_not_at_risk'][sim.ti] = np.count_nonzero(self.not_at_risk & sim.people.alive)
        self.results['prevalence'][sim.ti] = np.count_nonzero(self.affected & sim.people.alive)/np.count_nonzero(sim.people.alive)
        self.results['new_deaths'][sim.ti] = np.count_nonzero(self.ti_dead == sim.ti)
        return