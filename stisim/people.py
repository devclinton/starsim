"""
Defines the People class and functions associated with making people
"""

# %% Imports
import functools
import numpy as np
import sciris as sc
import stisim as ss


__all__ = ['State', 'BasePeople', 'People']


#%% States

class State(sc.prettyobj):
    def __init__(self, name, dtype, fill_value=0, shape=None, distdict=None, label=None):
        """
        Args:
            name: name of the result as used in the model
            dtype: datatype
            fill_value: default value for this state upon model initialization
            shape: If not none, set to match a string in `pars` containing the dimensionality
            label: text used to construct labels for the result for displaying on plots and other outputs
        """
        self.name = name
        self.dtype = dtype
        self.fill_value = fill_value
        self.shape = shape
        self.distdict = distdict
        self.is_dist = distdict is not None # Set this by default, but allow it to be overridden
        self.label = label or name
        return

    @property
    def ndim(self):
        return len(sc.tolist(self.shape)) + 1
    
    def new(self, n):
        if self.is_dist:
            return self.new_dist(n)
        else:
            return self.new_scalar(n)

    def new_scalar(self, n):
        shape = sc.tolist(self.shape)
        shape.append(n)
        out = np.full(shape, dtype=self.dtype, fill_value=self.fill_value)
        return out
    
    def new_dist(self, n):
        shape = sc.tolist(self.shape)
        shape.append(n)
        out = ss.sample(**self.distdict, size=tuple(shape))
        return out


base_states = ss.ndict(
    State('uid', int),
    State('age', float),
    State('female', bool, False),
    State('debut', float),
    State('alive', bool, True),
    State('ti_dead', float, np.nan),  # Time index for death
    State('scale', float, 1.0),
)


# %% Main people class

base_key = 'uid'  # Define the key used by default for getting length, etc.

class BasePeople(sc.prettyobj):
    """
    A class to handle all the boilerplate for people -- everything interesting 
    happens in the People class, whereas this class exists to handle the less 
    interesting implementation details.
    """

    def __len__(self):
        """ Length of people """
        return len(self[base_key])


    def _len_arrays(self):
        """ Length of underlying arrays """
        return len(self._data[base_key])
    

    def _grow(self, n):
        """
        Increase the number of agents stored

        Automatically reallocate underlying arrays if required
        
        Args:
            n (int): Number of new agents to add
        """
        orig_n = self._n
        new_total = orig_n + n
        if new_total > self._s:
            n_new = max(n, int(self._s / 2))  # Minimum 50% growth
            for state_name, state in self.states.items():
                self._data[state_name] = np.concatenate([self._data[state_name], state.new(n_new)],
                                                        axis=self._data[state_name].ndim - 1)
            self._s += n_new
        self._n += n
        self._map_arrays()
        new_inds = np.arange(orig_n, self._n)
        return new_inds


    def _map_arrays(self, keys=None):
        """
        Set main simulation attributes to be views of the underlying data

        This method should be called whenever the number of agents required changes
        (regardless of whether the underlying arrays have been resized)
        """
        
        # CK: consider refactor
        def rsetattr(obj, attr, val):
            pre, _, post = attr.rpartition('.')
            return setattr(rgetattr(obj, pre) if pre else obj, post, val)


        def rgetattr(obj, attr, *args):
            def _getattr(obj, attr):
                return getattr(obj, attr, *args)
            return functools.reduce(_getattr, [obj] + attr.split('.'))
        
        row_inds = slice(None, self._n)

        # Handle keys
        if keys is None: keys = self.states.keys()
        keys = sc.tolist(keys)

        # Map arrays for selected keys
        for k in keys:
            arr = self._data[k]
            if arr.ndim == 1:
                rsetattr(self, k, arr[row_inds])
            elif arr.ndim == 2:
                rsetattr(self, k, arr[:, row_inds])
            else:
                errormsg = 'Can only operate on 1D or 2D arrays'
                raise TypeError(errormsg)

        return


    def __getitem__(self, key):
        """
        Allow people['attr'] instead of getattr(people, 'attr')
        If the key is an integer, alias `people.person()` to return a `Person` instance
        """
        if isinstance(key, int):
            return self.person(key) # TODO: need to re-implement
        else:
            return self.__getattribute__(key)


    def __setitem__(self, key, value):
        """ Ditto """
        return self.__setattr__(key, value)


    def __iter__(self):
        """ Iterate over people """
        for i in range(len(self)):
            yield self[i]
            
            
    @property
    def active(self):
        """ Indices of everyone sexually active  """
        return (self.age >= self.debut) & self.alive
    
    
    @property
    def dead(self):
        """ Dead boolean """
        return ~self.alive



class People(BasePeople):
    """
    A class to perform all the operations on the people
    This class is usually created automatically by the sim. The only required input
    argument is the population size, but typically the full parameters dictionary
    will get passed instead since it will be needed before the People object is
    initialized.

    Note that this class handles the mechanics of updating the actual people, while
    ``ss.BasePeople`` takes care of housekeeping (saving, loading, exporting, etc.).
    Please see the BasePeople class for additional methods.

    Args:
        pars (dict): the sim parameters, e.g. sim.pars -- alternatively, if a number, interpreted as n_agents
        strict (bool): whether to only create keys that are already in self.meta.person; otherwise, let any key be set
        pop_trend (dataframe): a dataframe of years and population sizes, if available
        kwargs (dict): the actual data, e.g. from a popdict, being specified

    **Examples**::
        ppl = ss.People(2000)
    """

    # %% Basic methods

    def __init__(self, n, states=None, networks=None):
        """
        Initialize
        """
        
        self.initialized = False
        self.version = ss.__version__  # Store version info

        # Initialize states, networks, modules
        self.states = ss.ndict(base_states, states)
        self.networks = ss.ndict(networks)

        # Private variables relating to dynamic allocation
        self._data = dict()
        self._n = n  # Number of agents (initial)
        self._s = self._n  # Underlying array sizes
        self._inds = None  # No filtering indices

        # Initialize underlying storage and map arrays
        for state_name, state in self.states.items():
            self._data[state_name] = state.new(self._n)
        self._map_arrays()
        self['uid'][:] = np.arange(self._n)
        return


    def initialize(self, popdict=None):
        """ Initialize people by setting their attributes """
        if popdict is None: # TODO: update
            self['age'][:] = np.random.random(size=len(self)) * 100
            self['female'][:] = np.random.choice([False, True], size=len(self))
        else:
            # Use random defaults
            self['age'][:] = popdict['age']
            self['female'][:] = popdict['female']
        self.initialized = True
        return


    def add_module(self, module, force=False):
        # Initialize all the states associated with a module
        # This is implemented as People.add_module rather than
        # Module.add_to_people(people) or similar because its primary
        # role is to modify the People object
        if hasattr(self, module.name) and not force:
            raise Exception(f'Module {module.name} already added')
        self.__setattr__(module.name, sc.objdict())

        for state_name, state in module.states.items():
            combined_name = module.name + '.' + state_name
            self._data[combined_name] = state.new(self._n)
            self._map_arrays(keys=combined_name)
            self.states[combined_name] = state

        return


    def scale_flows(self, inds):
        """
        Return the scaled versions of the flows -- replacement for len(inds)
        followed by scale factor multiplication
        """
        return self.scale[inds].sum()
    
    
    def update(self, sim):
        """ Update demographics and networks """
        self.update_demographics(sim.dt, sim.ti)
        self.update_networks()
        return


    def update_demographics(self, dt, ti):
        """ Perform vital dynamic updates at the current timestep """
        self.age[self.alive] += dt
        self.alive[self.ti_dead <= ti] = False
        return
    

    def update_networks(self):
        """
        Update networks
        """
        for network in self.networks.values():
            network.update(self)