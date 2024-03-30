"""
Test SciPy distributions
"""

# %% Imports and settings
import numpy as np
import sciris as sc
import starsim as ss
import scipy.stats as sps
import pytest

n = 5


# %% Define the tests

def test_basic():
    """ Basic scipy.stats test """
    sc.heading('Test basic scipy.stats usage')
    spsdist = sps.norm(loc=1, scale=1) # Make a distribution
    d = ss.Dist(dist=spsdist).initialize(slots=np.arange(n)) # Convert it to Starsim
    sample = d.rvs(1)  # Draw a sample

    # Draw some samples
    d.reset()
    m = 10
    samples = d.rvs(m) # Draw several samples
    
    # Draw UID samples
    d.reset()
    uids = np.array([0,3,4])
    samples_uid = d.rvs(uids)
    
    # Print and test
    for s in [sample, samples, samples_uid]:
        print(s)
    assert sample == samples[0] == samples_uid[0], 'Samples should match after reset'
    assert len(samples) == m, 'Incorrect number of samples'
    assert len(samples_uid) == len(uids), 'Incorrect number of samples'
    
    return d


def test_scalar(n=n):
    """ Test a basic scalar distribution """
    sc.heading('Testing basic uniform distribution with scalar parameters')

    loc = 1
    scale = 4
    uids = np.array([1,3,5,9])
    
    spsdist = sps.uniform(loc=loc, scale=scale)
    d = ss.Dist(spsdist).initialize(slots=np.arange(uids.max()+1))
    
    draws = d.rvs(uids)
    print(f'Uniform sample for uids {uids} returned {draws}')

    assert len(draws) == len(uids), 'Incorrect number of draws'
    assert (draws.min() > loc) and (draws.max() < loc + scale), 'Values are out of bounds'
    
    return d


def test_callable(n=n):
    """ Test callable parameters """
    sc.heading('Testing a uniform distribution with callable parameters')
    
    # Define a fake people object
    np.random.seed(1) # Since not random number safe here!
    sim = sc.prettyobj()
    sim.n = 10
    sim.people = sc.prettyobj()
    sim.people.uid = np.arange(sim.n)
    sim.people.slot = np.arange(sim.n)
    sim.people.age = np.random.uniform(0, 90, size=sim.n)

    # Define a parameter as a lambda function
    loc = lambda module, sim, uids: sim.people.age[uids]
    scale = 1
    d = ss.normal(loc=loc).initialize(sim=sim)

    uids = np.array([1, 3, 7, 9])
    draws = d.rvs(uids)
    print(f'Input ages were: {sim.people.age[uids]}')
    print(f'Output samples were: {draws}')

    meandiff = np.abs(sim.people.age[uids] - draws).mean()
    assert meandiff < scale*3
    return d


def test_array(n=n):
    """ Test array parameters """
    sc.heading('Testing uniform with a array parameters')

    uids = np.array([1, 3])
    low  = np.array([1, 100]) # Low
    high = np.array([3, 125]) # High

    d = ss.uniform(low=low, high=high).initialize(slots=np.arange(uids.max()+1))
    draws = d.rvs(uids)
    print(f'Uniform sample for uids {uids} returned {draws}')

    assert len(draws) == len(uids)
    for i in range(len(uids)):
        assert low[i] < draws[i] < low[i] + high[i], 'Invalid value'
    return draws


@pytest.mark.skip
def test_repeat_slot():
    """ Test behavior of repeated slots """
    sc.heading('Test behavior of repeated slots')

    # Initialize parameters
    slots = np.array([4,2,3,2,2,3])
    n = len(slots)
    uids = np.arange(n)
    low = np.arange(n)
    high = low + 1

    # Draw values
    d = ss.uniform(low=low, high=high).initialize()
    draws = d.rvs(uids)
    
    # Print and test
    print(f'Uniform sample for slots {slots} returned {draws}')
    assert len(draws) == len(slots)

    unique_slots = np.unique(slots)
    for s in unique_slots:
        inds = np.where(slots==s)[0]
        frac, integ = np.modf(draws[inds])
        assert np.allclose(integ, low[inds]), 'Integral part should match the low parameter'
        assert np.allclose(frac, frac[0]), 'Same random numbers, so should be same fractional part'
    return draws



# %% Run as a script
if __name__ == '__main__':
    
    T = sc.timer()

    o1 = test_basic()
    o2 = test_scalar(n)
    o3 = test_callable(n)
    o4 = test_array(n)
    # o5 = test_repeat_slot() # TODO: confirm behavior and reimplement

    T.toc()
