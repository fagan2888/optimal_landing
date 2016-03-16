"""
Implements an indirect method to solve the optimal control problem of a 
three engine spacecraft (Model 2)

Dario Izzo 2016

"""

from PyGMO.problem._base import base
from numpy.linalg import norm
from math import sqrt, sin, cos, atan2
from scipy.integrate import odeint
from numpy import linspace
from copy import deepcopy


class simple_landing(base):

	def __init__(
			self,
			state0 = [0., 1000., 20., -5., 10000.],
			statet = [0., 0., 0., 0, 9758.695805],
			Isp=311.,
			c=44000.,
			g = 1.6229,
			objfun_type = "QC",
			pinpoint = False
			):
		"""
		USAGE: reachable(self, start, end, Isp, Tmax, mu):

		* state0: initial state [x, y, vx, vy, theta, vtheta, m] in m,m,m/s,m/s,rad,rad/s,kg
		* statet: target state [x, y, vx, vy, theta, vtheta, m] in m,m,m/s,m/s,rad,rad/s,kg
		* Isp: engine specific impulse (sec.)
		* c: maximum thrusts for the main thruster (N)
		* g: planet gravity [m/s**2]
		"""

		super(simple_landing, self).__init__(6, 0, 1, 6, 0, 1e-8)

		# We store the raw inputs for convenience
		self.state0_input = state0
		self.statet_input = statet

		# We compute the non dimensional units
		self.R = 1000.
		self.V = 100.
		self.M = 10000.
		self.A = (self.V * self.V) / self.R
		self.T = self.R / self.V
		self.F = self.M * self.A

		# We store the parameters
		self.Isp = Isp / self.T
		self.c = c / self.F
		self.g = g / self.A
		self.G0 =  9.81 / self.A

		# We compute the initial and final state in the new units
		self.state0 = self._non_dim(self.state0_input)
		self.statet = self._non_dim(self.statet_input)

		# We set the bounds (these will only be used to initialize the population)
		self.set_bounds([-1.] * 5 + [1e-04], [1.] * 5 + [100. / self.T])

		# This switches between MOC and QC
		self.objfun_type = objfun_type

		# Activates a pinpoint landing
		self.pinpoint = pinpoint

	def _objfun_impl(self, x):
		#xf, info = self._shoot(x)
		return(1.,) # constraint satisfaction

	def _compute_constraints_impl(self, x):
		# Perform one forward shooting
		xf, info = self._shoot(x)

		# Assembling the equality constraint vector
		ceq = list([0]*6)
		# Final conditions
		ceq[1] = (xf[-1][1] - self.statet[1] ) * 100.
		ceq[2] = (xf[-1][2] - self.statet[2] ) * 100.
		ceq[3] = (xf[-1][3] - self.statet[3] ) * 100.
		

		# Transversality condition on mass (free)
		#ceq[0] = xf[-1][5] * 100.
		ceq[4] = xf[-1][9] * 100.

		if self.pinpoint:
			#Pinpoint landing x is fixed lx is free
			ceq[0] = (xf[-1][0] - self.statet[0] ) * 100
		else:
			#Transversality condition: x is free lx is 0
			ceq[0] = xf[-1][5] * 100.

		# Free time problem, Hamiltonian must be 0
		ceq[5] = self._hamiltonian(xf[-1]) * 100.

		return ceq

	def _hamiltonian(self, full_state):

		state = full_state[:5]
		costate = full_state[5:]

		# Applying Pontryagin minimum principle
		controls = self._pontryagin_minimum_principle(full_state)

		# Computing the R.H.S. of the state eom
		f_vett = self._eom_state(state, controls)

		# Assembling the Hamiltonian
		H = 0.
		for l, f in zip(costate, f_vett):
			H += l * f

		# Adding the integral cost function (WHY -)
		H += self._cost(state, controls)
		return H

	def _cost(self,state, controls):
		Isp, g0 = [self.Isp, self.G0]
		c = self.c
		u, stheta, ctheta = controls

		if self.objfun_type == "QC":
			# Quadratic Control
			retval = c**2 / Isp / g0 * u**2
		elif self.objfun_type == "MOC":
			# Mass Optimal
			retval = c / Isp / g0 * u
		return retval

	def _eom_state(self, state, controls):
		# Renaming variables
		x,y,vx,vy,m = state
		Isp, g0, g = [self.Isp, self.G0, self.g]
		c = self.c
		u, stheta, ctheta = controls

		# Equations for the state
		dx = vx
		dy = vy
		dvx = c * u / m * stheta
		dvy = c * u / m * ctheta - g
		dm = - c * u / Isp / g0
		return [dx, dy, dvx, dvy, dm]

	def _eom_costate(self, full_state, controls):
		# Renaming variables
		x,y,vx,vy,m,lx,ly,lvx,lvy,lm = full_state
		Isp, g0 = [self.Isp, self.G0]
		c = self.c
		u, stheta, ctheta = controls

		# Equations for the costate
		lvdotitheta = lvx * stheta + lvy * ctheta

		dlx = 0.
		dly = 0.
		dlvx = - lx
		dlvy = - ly
		dlm =  c * u / m**2 * lvdotitheta
		
		return [dlx, dly, dlvx, dlvy, dlm]

	def _pontryagin_minimum_principle(self, full_state):
		# Renaming variables
		Isp, g0  = [self.Isp, self.G0]
		c = self.c
		x,y,vx,vy,m,lx,ly,lvx,lvy,lm = full_state

		lv_norm = sqrt(lvx**2 + lvy**2)
		stheta = - lvx / lv_norm
		ctheta = - lvy / lv_norm

		if self.objfun_type == "QC":
			# Quadratic Control
			u = 1. / c * (lm + lv_norm * Isp * g0 / m)
			u = min(u,1.)
			u = max(u,0.)
		elif self.objfun_type == "MOC":
			# Minimum mass
			S = 1. - lm - lv_norm / m * Isp * g0
			if S >= 0:
				u=0.
			if S < 0:
				u=1.
		return [u, stheta, ctheta]

	def _eom(self, full_state, t):
		# Applying Pontryagin minimum principle
		state = full_state[:5]
		controls = self._pontryagin_minimum_principle(full_state)
		# Equations for the state
		dstate = self._eom_state(state, controls)
		# Equations for the co-states
		dcostate = self._eom_costate(full_state, controls)
		return dstate + dcostate

	def _shoot(self, x):
		# Numerical Integration
		xf, info = odeint(lambda a,b: self._eom(a,b), self.state0 + list(x[:-1]), [0, x[-1]], rtol=1e-12, atol=1e-12, full_output=1, mxstep=2000)
		return xf, info

	def _simulate(self, x, tspan):
		# Numerical Integration
		xf, info = odeint(lambda a,b: self._eom(a,b), self.state0 + list(x[:-1]), tspan, rtol=1e-12, atol=1e-12, full_output=1, mxstep=2000)
		return xf, info

	def _non_dim(self, state):
		xnd = deepcopy(state)
		xnd[0] /= self.R
		xnd[1] /= self.R
		xnd[2] /= self.V
		xnd[3] /= self.V
		xnd[4] /= self.M
		return xnd

	def _dim_back(self, state):
		xd = deepcopy(state)
		xd[0] *= self.R
		xd[1] *= self.R
		xd[2] *= self.V
		xd[3] *= self.V
		xd[4] *= self.M
		return xd

	def plot(self, x):
		import matplotlib as mpl
		from mpl_toolkits.mplot3d import Axes3D
		import matplotlib.pyplot as plt
		mpl.rcParams['legend.fontsize'] = 10

		# Producing the data
		tspan = linspace(0, x[-1], 100)
		full_state, info = self._simulate(x, tspan)
		# Putting dimensions back
		res = list()
		controls = list()
		ux = list(); uy=list()
		for line in full_state:
			res.append(self._dim_back(line[:7]))
			controls.append(self._pontryagin_minimum_principle(line))
			ux.append(controls[-1][0]*controls[-1][1])
			uy.append(controls[-1][0]*controls[-1][2])
		tspan = [it * self.T for it in tspan]

		x = list(); y=list()
		vx = list(); vy = list()
		m = list()
		for state in res:
			x.append(state[0])
			y.append(state[1])
			vx.append(state[2])
			vy.append(state[3])
			m.append(state[4])

		fig = plt.figure()
		ax = fig.gca()
		ax.plot(x, y, color='r', label='Trajectory')
		ax.quiver(x, y, ux, uy, label='Thrust', pivot='tail', width=0.001)
		ax.set_ylim(0,self.state0_input[1]+500)

		f, axarr = plt.subplots(3, 2)

		axarr[0,0].plot(x, y)
		axarr[0,0].set_xlabel('x'); axarr[0,0].set_ylabel('y'); 

		axarr[1,0].plot(vx, vy)
		axarr[1,0].set_xlabel('vx'); axarr[1,0].set_ylabel('vy');

		axarr[2,0].plot(tspan, m)

		axarr[0,1].plot(tspan, [controls[ix][0] for ix in range(len(controls))],'r')
		axarr[0,1].set_ylabel('u')
		axarr[0,1].set_xlabel('t')
		axarr[1,1].plot(tspan, [atan2(controls[ix][1], controls[ix][2]) for ix in range(len(controls))],'k')
		axarr[1,1].set_ylabel('theta')
		axarr[1,1].set_xlabel('t')
		axarr[2,1].plot(tspan, [controls[ix][2] for ix in range(len(controls))],'k')


		plt.ion()
		plt.show()
		return axarr

	def human_readable_extra(self):
		s = "\n\tDimensional inputs:\n"
		s = s + "\tStarting state: " + str(self.state0_input) + "\n"
		s = s + "\tTarget state: " + str(self.statet_input) + "\n"
		s = s + "\tThrusters maximum magnitude [N]: " + str(self.c * self.F) + "\n"
		s = s + "\tIsp: " + str(self.Isp * self.T) + ", gravity: " + str(self.g * self.A) + "\n"

		s = s + "\n\tNon - Dimensional inputs:\n"
		s = s + "\tStarting state: " + str(self.state0) + "\n"
		s = s + "\tTarget state: " + str(self.statet) + "\n"
		s = s + "\tThrusters maximum magnitude [N]: " + str(self.c) + "\n"
		s = s + "\tIsp: " + str(self.Isp) + ", gravity: " + str(self.g) + "\n\n"
		
		s = s + "\tObjective function: " + self.objfun_type + "\n"
		s = s + "\tPinpoint?: " + str(self.pinpoint)

		return s

if __name__ == "__main__":
	from PyGMO import *
	from random import random
	algo = algorithm.snopt(200, opt_tol=1e-4, feas_tol=1e-9)
	#algo = algorithm.scipy_slsqp(max_iter = 1000,acc = 1E-8,epsilon = 1.49e-08, screen_output = True)
	#algo.screen_output = True

	# Pinpoint
	x0 = random() * (10. + 10.) -10.
	y0 = random() * (2000. - 500.) + 500.
	m0 = random() * (12000. - 8000.) + 8000.
	vx0 = random() * (10. + 10.) - 10.
	vy0 = random() * (10. + 30.) - 30.
	state0 = [x0, y0, vx0, vy0, m0]

	# Free
	#x0 = 0. #irrelevant
	#y0 = random() * (2000. - 500.) + 500.
	#m0 = random() * (12000. - 8000.) + 8000.
	#vx0 = random() * (100. + 100.) - 100.
	#vy0 = random() * (10. + 30.) - 30.
	#state0 = [x0, y0, vx0, vy0, m0]


	print("Trying I.C. {}".format(state0)),
	probMOC = simple_landing(state0 = state0, objfun_type="MOC", pinpoint=True)
	count = 1
	for i in range(1, 20):
		print("Attempt # {}".format(i))
		popMOC = population(probMOC,1)
		popMOC = algo.evolve(popMOC)
		if (probMOC.feasibility_x(popMOC[0].cur_x)):
			break

	print(probMOC.feasibility_x(popMOC[0].cur_x))