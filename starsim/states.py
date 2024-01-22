import pandas as pd
import numpy as np
import sciris as sc
import numba as nb
from starsim.utils import INT_NAN
from starsim.distributions import ScipyDistribution
from starsim.utils import warn
from numpy.lib.mixins import NDArrayOperatorsMixin  # Inherit from this to automatically gain operators like +, -, ==, <, etc.
from scipy.stats._distn_infrastructure import rv_frozen

__all__ = ['State', 'DynamicView']



class FusedArray(NDArrayOperatorsMixin):
    # This is a class that allows indexing by UID but does not support dynamic growth
    # It's kind of like a Pandas series but one that only supports a monotonically increasing
    # unique integer index, and that we can customize and optimize indexing for.
    #
    # We explictly do NOT support slicing (except for `[:]`), as these arrays are indexed by UID and slicing
    # by UID can be confusing/ambiguous when there are missing values. Indexing with a list/array returns
    # another FusedArray instance which enables chained filtering

    __slots__ = ('values','_uid_map', 'uid')

    def __init__(self, values, uid, uid_map=None):

        self.values = values
        self.uid = uid

        if uid_map is None and uid is not None:
            # Construct a local UID map as opposed to using a shared one (i.e., the one for all agents contained in the People instance)
            self.uid_map = np.full(np.max(uid) + 1, fill_value=INT_NAN, dtype=int)
            self.uid_map[uid] = np.arange(len(uid))
        else:
            self._uid_map = uid_map

    def __repr__(self):
        # TODO - optimize? Don't really need to create a dataframe just to print it, but on the other hand, it's fast enough and very easy
        df = pd.DataFrame(self.values.T, index=self.uid, columns=['Quantity'])
        df.index.name = 'UID'
        return df.__repr__()

    @property
    def dtype(self):
        return self.values.dtype

    @staticmethod
    @nb.njit
    def _get_vals_uids(vals, key, uid_map):
        """
        Extract values from a collection of UIDs

        This function is used to retrieve values based on UID. As indexing a FusedArray returns a new FusedArray,
        this method also populates the new UID map for use in the subsequently created FusedArray, avoiding the
        need to re-compute it separately.

        :param vals: A 1D np.ndarray containing the values
        :param key: A 1D np.ndnarray of integers containing the UIDs to query
        :param uid_map: A 1D np.ndarray of integers mapping UID to array position in ``vals``
        :return: A tuple of (values, uids, new_uid_map) suitable for passing into the FusedArray constructor
        """
        out = np.empty(len(key), dtype=vals.dtype)
        new_uid_map = np.full(uid_map.shape[0], fill_value=INT_NAN, dtype=np.int64)

        for i in range(len(key)):
            idx = uid_map[key[i]]
            if idx == INT_NAN:
                raise IndexError('UID not present in array')
            out[i] = vals[idx]
            new_uid_map[key[i]] = i
        return out, key, new_uid_map

    @staticmethod
    @nb.njit
    def _set_vals_uids_multiple(vals, key, uid_map, value):
        """
        Insert an array of values based on UID

        :param vals: A reference to a 1D np.ndarray in which to insert the values
        :param key: A 1D np.ndnarray of integers containing the UIDs to add values for
        :param uid_map:  A 1D np.ndarray of integers mapping UID to array position in ``vals``
        :param value: A 1D np.ndarray the same length as ``key`` containing values to insert
        :return:
        """

        for i in range(len(key)):
            if key[i] >= len(uid_map):
                raise IndexError('UID not present in array (requested UID is larger than the maximum UID in use)')
            idx = uid_map[key[i]]
            if idx == INT_NAN:
                raise IndexError('UID not present in array')
            elif idx >= len(vals):
                raise Exception(f'Attempted to write to a non-existant index - this can happen if attempting to write to new entries that have not yet been allocated via grow()')
            vals[idx] = value[i]

    @staticmethod
    @nb.njit
    def _set_vals_uids_single(vals, key, uid_map, value):
        """
        Insert a single value into multiple UIDs

        :param vals: A reference to a 1D np.ndarray in which to insert the values
        :param key: A 1D np.ndnarray of integers containing the UIDs to add values for
        :param uid_map:  A 1D np.ndarray of integers mapping UID to array position in ``vals``
        :param value: A scalar value to insert at every position specified by ``key``
        :return:
        """
        for i in range(len(key)):
            if key[i] >= len(uid_map):
                raise IndexError('UID not present in array (requested UID is larger than the maximum UID in use)')
            idx = uid_map[key[i]]
            if idx == INT_NAN:
                raise IndexError('UID not present in array')
            elif idx >= len(vals):
                raise Exception('Attempted to write to a non-existant index - this can happen if attempting to write to new entries that have not yet been allocated via grow()')
            vals[idx] = value

    def __getitem__(self, key):
        try:
            if isinstance(key, (int, np.integer)):
                # Handle getting a single item by UID
                return self.values[self._uid_map[key]]
            elif isinstance(key, (np.ndarray, FusedArray, DynamicView)):
                if key.dtype.kind == 'b':
                    # Handle accessing items with a logical array. Surprisingly, it seems faster to use nonzero() to convert
                    # it to indices first. Also, the pure Python implementation is difficult to improve upon using numba
                    mapped_key = key.__array__().nonzero()[0]
                    uids = self.uid.__array__()[mapped_key]
                    new_uid_map = np.full(len(self._uid_map), fill_value=INT_NAN, dtype=int)
                    new_uid_map[uids] = np.arange(len(uids))
                    values = self.values[mapped_key]
                else:
                    # Access items by an array of integers. We do get a decent performance boost from using numba here
                    values, uids, new_uid_map = self._get_vals_uids(self.values, key.__array__(), self._uid_map.__array__())
            elif isinstance(key, slice):
                if key.start is None and key.stop is None and key.step is None:
                    return sc.dcp(self)
                else:
                    raise Exception('Slicing not supported - slice the .values attribute by index instead e.g., x.values[0:5], not x[0:5]')
            else:
                # This branch is specifically handling the user passing in a list of integers instead of an array, therefore
                # we need an additional conversion to an array first using np.fromiter to improve numba performance
                values, uids, new_uid_map = self._get_vals_uids(self.values, np.fromiter(key, dtype=int), self._uid_map.__array__())
            return FusedArray(values=values, uid=uids, uid_map=new_uid_map)
        except IndexError as e:
            if str(INT_NAN) in str(e):
                raise IndexError(f'UID not present in array')
            else:
                raise e

    def __setitem__(self, key, value):
        # nb. the use of .__array__() calls is to access the array interface and thereby treat both np.ndarray and DynamicView instances
        # in the same way without needing an additional type check. This is also why the FusedArray.dtype property is defined. Noting
        # that for a State, the uid_map is a dynamic view attached to the People, but after an indexing operation, it will be a bare
        # FusedArray that has an ordinary numpy array as the uid_map
        try:
            if isinstance(key, (int, np.integer)):
                return self.values.__setitem__(self._uid_map[key], value)
            elif isinstance(key, (np.ndarray, FusedArray)):
                if key.dtype.kind == 'b':
                    self.values.__setitem__(key.__array__().nonzero()[0], value)
                else:
                    if isinstance(value, (np.ndarray, FusedArray)):
                        return self._set_vals_uids_multiple(self.values, key, self._uid_map.__array__(), value.__array__())
                    else:
                        return self._set_vals_uids_single(self.values, key, self._uid_map.__array__(), value)
            elif isinstance(key, slice):
                if key.start is None and key.stop is None and key.step is None:
                    return self.values.__setitem__(key, value)
                else:
                    raise Exception('Slicing not supported - slice the .values attribute by index instead e.g., x.values[0:5], not x[0:5]')
            else:
                if isinstance(value, (np.ndarray, FusedArray)):
                    return self._set_vals_uids_multiple(self.values, np.fromiter(key, dtype=int), self._uid_map.__array__(), value.__array__())
                else:
                    return self._set_vals_uids_single(self.values, np.fromiter(key, dtype=int), self._uid_map.__array__(), value)
        except IndexError as e:
            if str(INT_NAN) in str(e):
                raise IndexError(f'UID not present in array')
            else:
                raise e

    # Make it behave like a regular array mostly
    def __len__(self):
        return len(self.values)

    def __contains__(self, *args, **kwargs):
        return self.values.__contains__(*args, **kwargs)

    def astype(self, *args, **kwargs):
        return FusedArray(values=self.values.astype(*args, **kwargs), uid=self.uid, uid_map=self._uid_map)

    def sum(self, *args, **kwargs):
        return self.values.sum(*args, **kwargs)

    def mean(self, *args, **kwargs):
        return self.values.mean(*args, **kwargs)

    def any(self, *args, **kwargs):
        return self.values.any(*args, **kwargs)

    def all(self, *args, **kwargs):
        return self.values.all(*args, **kwargs)

    def count_nonzero(self, *args, **kwargs):
        return np.count_nonzero(self.values, *args, **kwargs)

    @property
    def shape(self):
        return self.values.shape

    @property
    def __array_interface__(self):
        return self.values.__array_interface__

    def __array__(self):
        return self.values

    def __array_ufunc__(self, *args, **kwargs):
        if args[1] != '__call__':
            # This is a generic catch-all for ufuncs that are not being applied with '__call__' (e.g., operations returning a scalar like 'np.sum()' use reduce instead)
            args = [(x if x is not self else self.values) for x in args]
            kwargs = {k: v if v is not self else self.values for k, v in kwargs.items()}
            return self.values.__array_ufunc__(*args, **kwargs)

        args = [(x if x is not self else self.values) for x in args]
        if 'out' in kwargs and kwargs['out'][0] is self:
            # In-place operations like += use this branch
            kwargs['out'] = self.values
            args[0](*args[2:], **kwargs)
            return self
        else:
            out = args[0](*args[2:], **kwargs)
            if isinstance(out, FusedArray):
                # For some operations (e.g., those involving two FusedArrays) the result of the ufunc will already be a FusedArray
                # In particular, operating on two states will result in a FusedArray where the references to the original People uid_map and uids
                # are still intact. In such cases, we can return the resulting FusedArray directly
                return out
            else:
                # Otherwise, if the result of the ufunc is an array (e.g., because one of the arguments was an array) then
                # we need to wrap it up in a new FusedArray. With '__call__' the dimensions should hopefully be the same and we should
                # be able to reuse the UID arrays directly
                return FusedArray(values=out, uid=self.uid, uid_map=self._uid_map)

    def __array_wrap__(self, out_arr, context=None):
        # This allows numpy operations addition etc. to return instances of FusedArray
        if out_arr.ndim == 0:
            return out_arr.item()
        return FusedArray(values=out_arr, uid=self.uid, uid_map=self._uid_map) # Hardcoding class means State can inherit from FusedArray but return FusedArray base instances


class DynamicView(NDArrayOperatorsMixin):
    def __init__(self, dtype, fill_value=None):
        """
        Args:
            name: name of the result as used in the model
            dtype: datatype
            fill_value: default value for this state upon model initialization. If not provided, it will use the default value for the dtype
            shape: If not none, set to match a string in `pars` containing the dimensionality
            label: text used to construct labels for the result for displaying on plots and other outputs
        """
        self.fill_value = fill_value if fill_value is not None else dtype()
        self.n = 0  # Number of agents currently in use
        self._data = np.empty(0, dtype=dtype)  # The underlying memory array (length at least equal to n)
        self._view = None  # The view corresponding to what is actually accessible (length equal to n)
        self._map_arrays()
        return

    @property
    def _s(self):
        # Return the size of the underlying array (maximum number of agents that can be stored without reallocation)
        return len(self._data)

    @property
    def dtype(self):
        # The specified dtype and the underlying array dtype can be different. For instance, the user might pass in
        # DynamicView(dtype=int) but the underlying array's dtype will be np.dtype('int32'). This distinction is important
        # because the numpy dtype has attributes like 'kind' that the input dtype may not have. We need the DynamicView's
        # dtype to match that of the underlying array so that it can be more seamlessly exchanged with direct numpy arrays
        # Therefore, we retain the original dtype in DynamicView._dtype() and use
        return self._data.dtype

    def __len__(self):
        # Return the number of active elements
        return self.n

    def __repr__(self):
        # Print out the numpy view directly
        return self._view.__repr__()

    def grow(self, n):
        # If the total number of agents exceeds the array size, extend the underlying arrays
        if self.n + n > self._s:
            n_new = max(n, int(self._s / 2))  # Minimum 50% growth
            self._data = np.concatenate([self._data, np.full(n_new, dtype=self.dtype, fill_value=self.fill_value)], axis=0)
        self.n += n  # Increase the count of the number of agents by `n` (the requested number of new agents)
        self._map_arrays()

    def _trim(self, inds):
        # Keep only specified indices
        # Note that these are indices, not UIDs!
        n = len(inds)
        self._data[:n] = self._data[inds]
        self._data[n:self.n] = self.fill_value
        self.n = n
        self._map_arrays()

    def _map_arrays(self):
        """
        Set main simulation attributes to be views of the underlying data

        This method should be called whenever the number of agents required changes
        (regardless of whether or not the underlying arrays have been resized)
        """
        self._view = self._data[:self.n]

    def __getitem__(self, key):
        return self._view.__getitem__(key)

    def __setitem__(self, key, value):
        self._view.__setitem__(key, value)

    @property
    def __array_interface__(self):
        return self._view.__array_interface__

    def __array__(self):
        return self._view

    def __array_ufunc__(self, *args, **kwargs):
        args = [(x if x is not self else self._view) for x in args]
        kwargs = {k: v if v is not self else self._view for k, v in kwargs.items()}
        return self._view.__array_ufunc__(*args, **kwargs)


class State(FusedArray):

    def __init__(self, name, dtype, fill_value=None, label=None):
        """

        :param name: A string name for the state
        :param dtype: The dtype to use for this instance
        :param fill_value: Specify default value for new agents. This can be
            - A scalar with the same dtype (or castable to the same dtype) as the State
            - A callable, with a single argument for the number of values to produce
            - An ss.ScipyDistribution instance
        :param label:
        """

        super().__init__(values=None, uid=None, uid_map=None)  # Call the FusedArray constructor

        self.fill_value = fill_value

        self._data = DynamicView(dtype=dtype)
        self.name = name
        self.label = label or name
        self.values = self._data._view
        self._initialized = False

    def __repr__(self):
        if not self._initialized:
            return f'<State {self.name} (uninitialized)>'
        else:
            return FusedArray.__repr__(self)

    def _new_vals(self, uids):
        if isinstance(self.fill_value, ScipyDistribution):
            new_vals = self.fill_value.rvs(uids)
        elif callable(self.fill_value):
            new_vals = self.fill_value(len(uids))
        else:
            new_vals = self.fill_value
        return new_vals

    def initialize(self, sim=None, people=None):
        if self._initialized:
            return

        if sim is not None and people is None:
            people = sim.people

        sim_still_needed = False
        if isinstance(self.fill_value, rv_frozen):
            if sim is not None:
                self.fill_value = ScipyDistribution(self.fill_value, f'{self.__class__.__name__}_{self.label}')
                self.fill_value.initialize(sim, self)
            else:
                sim_still_needed = True

        people.add_state(self, die=False) # CK: should not be needed
        if not sim_still_needed:
            self._uid_map = people._uid_map
            self.uid = people.uid
            self._data.grow(len(self.uid))
            self._data[:len(self.uid)] = self._new_vals(self.uid)
            self.values = self._data._view
            self._initialized = True
        return

    def grow(self, uids):
        """
        Add state for new agents

        This method is normally only called via `People.grow()`.

        :param uids: Numpy array of UIDs for the new agents being added This array should have length n
        """

        n = len(uids)
        self._data.grow(n)
        self.values = self._data._view
        self._data[-n:] = self._new_vals(uids)
        return

    def _trim(self, inds):
        # Trim arrays to remove agents - should only be called via `People.remove()`
        self._data._trim(inds)
        self.values = self._data._view
        return