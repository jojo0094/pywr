import numpy as np
import platypus
from . import cache_constraints, cache_objectives, cache_variable_parameters, BaseOptimisationWrapper

import logging
logger = logging.getLogger(__name__)


def count_constraints(constraints):
    """Count the number of constraints.

     Recorders that are doubled bounded will create two constraints in the platypus problem.
     """
    count = 0
    for c in constraints:
        if c.is_double_bounded_constraint:
            count += 2
        elif c.is_constraint:
            count += 1
        else:
            raise ValueError(f'Constraint "{c.name}" has no bounds defined.')
    return count


class PlatypusWrapper(BaseOptimisationWrapper):
    """ A helper class for running pywr optimisations with platypus.
    """
    def __init__(self, *args, **kwargs):
        super(PlatypusWrapper, self).__init__(*args, **kwargs)

        # To determine the number of variables, etc
        m = self.model

        # Cache the variables, objectives and constraints
        variables, variable_map = cache_variable_parameters(m)
        objectives = cache_objectives(m)
        constraints = cache_constraints(m)

        if len(variables) < 1:
            raise ValueError('At least one variable must be defined.')

        if len(objectives) < 1:
            raise ValueError('At least one objective must be defined.')

        self.problem = platypus.Problem(variable_map[-1], len(objectives), count_constraints(constraints))
        self.problem.function = self.evaluate
        self.problem.wrapper = self

        # Setup the problem; subclasses can change this behaviour
        self._make_variables(variables)
        self._make_constraints(constraints)

    def _make_variables(self, variables):
        """Setup the variable types. """

        ix = 0
        for var in variables:
            if var.double_size > 0:
                lower = var.get_double_lower_bounds()
                upper = var.get_double_upper_bounds()
                for i in range(var.double_size):
                    self.problem.types[ix] = platypus.Real(lower[i], upper[i])
                    ix += 1

            if var.integer_size > 0:
                lower = var.get_integer_lower_bounds()
                upper = var.get_integer_upper_bounds()
                for i in range(var.integer_size):
                    # Integers are cast to real
                    self.problem.types[ix] = platypus.Real(lower[i], upper[i])
                    ix += 1

    def _make_constraints(self, constraints):
        """ Setup the constraints. """

        ic = 0  # platypus constraint index
        for c in constraints:
            if c.is_double_bounded_constraint:
                # Need to create two constraints
                self.problem.constraints[ic] = platypus.Constraint('>=', value=c.constraint_lower_bounds)
                self.problem.constraints[ic + 1] = platypus.Constraint('<=', value=c.constraint_upper_bounds)
                ic += 2
            elif c.is_equality_constraint:
                self.problem.constraints[ic] = platypus.Constraint('==', value=c.constraint_lower_bounds)
                ic += 1
            elif c.is_lower_bounded_constraint:
                self.problem.constraints[ic] = platypus.Constraint('>=', value=c.constraint_lower_bounds)
                ic += 1
            elif c.is_upper_bounded_constraint:
                self.problem.constraints[ic] = platypus.Constraint('<=', value=c.constraint_upper_bounds)
                ic += 1
            else:
                raise RuntimeError(f'The bounds if constraint "{c.name}" could not be identified correctly.')

    def evaluate(self, solution):
        logger.info('Evaluating solution ...')

        for ivar, var in enumerate(self.model_variables):
            j = slice(self.model_variable_map[ivar], self.model_variable_map[ivar+1])
            x = np.array(solution[j])
            assert len(x) == var.double_size + var.integer_size
            if var.double_size > 0:
                var.set_double_variables(np.array(x[:var.double_size]))

            if var.integer_size > 0:
                ints = np.round(np.array(x[-var.integer_size:])).astype(np.int32)
                var.set_integer_variables(ints)

        run_stats = self.model.run()

        objectives = []
        for r in self.model_objectives:
            sign = 1.0 if r.is_objective == 'minimise' else -1.0
            value = r.aggregated_value()
            objectives.append(sign*value)

        constraints = []
        for c in self.model_constraints:
            x = c.aggregated_value()
            if c.is_double_bounded_constraint:
                # Double bounded recorder is translated to two platypus constraints.
                constraints.extend([x, x])
            else:
                constraints.append(x)

        # Return values to the solution
        logger.info('Evaluation complete!')
        if len(constraints) > 0:
            return objectives, constraints
        else:
            return objectives
