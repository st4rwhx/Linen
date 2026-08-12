--!strict
--[[
	Weight: the body resists its own changes of direction.

	Stock Roblox locomotion reaches full speed and full stop within a frame, and
	no amount of animation quality hides that — the giveaway is not the legs, it
	is the torso staying vertical while the character's velocity does something
	violent.

	So this leans the spine against acceleration. Speeding up, the chest goes
	forward of the hips; braking, it drops behind them and the character visibly
	fights its own momentum; turning hard, it banks into the corner. All of it
	is read from the assembly's actual velocity rather than from which animation
	is playing, which is what keeps it right during transitions — the moment
	blending usually gives up.

	It is a *correction on top of* the animation, applied by multiplying the
	Motor6D transforms the Animator has already written. Run it from PreRender,
	which is after that, and it layers instead of fighting.
]]

local RunService = game:GetService("RunService")

local Momentum = {}
Momentum.__index = Momentum

export type Config = {
	--[[ Degrees of lean per stud/second² of acceleration. ]]
	leanPerAcceleration: number,
	--[[ Degrees of bank per (radian/second × stud/second) of cornering. ]]
	bankPerTurn: number,
	--[[ Caps, because a lean that keeps growing eventually looks like a bug. ]]
	maxLean: number,
	maxBank: number,
	--[[ Seconds for the lean to catch up. This is the inertia: too low and the
	     lean snaps with the input, which defeats the point. ]]
	smoothing: number,
	--[[ Share of the lean the pelvis takes; the chest takes the rest. Splitting
	     it across two joints is what makes it read as a spine bending rather
	     than a plank tipping. ]]
	pelvisShare: number,
}

local DEFAULTS: Config = {
	leanPerAcceleration = 0.32,
	bankPerTurn = 1.6,
	maxLean = 18,
	maxBank = 14,
	smoothing = 0.14,
	pelvisShare = 0.35,
}

local SPINE = {
	R15 = { pelvis = "LowerTorso", chest = "UpperTorso" },
	R6 = { pelvis = "Torso", chest = "Torso" },
}

export type Momentum = typeof(setmetatable(
	{} :: {
		character: Model,
		root: BasePart,
		config: Config,
		pelvis: Motor6D?,
		chest: Motor6D?,
		weight: number,
		lean: number,
		bank: number,
		_lastVelocity: Vector3,
		_lastFacing: Vector3,
		_connection: RBXScriptConnection?,
	},
	Momentum
))

local function motorFor(character: Model, partName: string): Motor6D?
	local part = character:FindFirstChild(partName)
	if part == nil then
		return nil
	end
	for _, child in part:GetChildren() do
		if child:IsA("Motor6D") and child.Part1 == part then
			return child
		end
	end
	return nil
end

function Momentum.new(character: Model, rigName: string, config: Config?): Momentum?
	local root = character:FindFirstChild("HumanoidRootPart")
	local spine = SPINE[rigName]
	if not (root and root:IsA("BasePart") and spine) then
		return nil
	end

	local merged: Config = table.clone(DEFAULTS)
	if config then
		for key, value in config :: any do
			(merged :: any)[key] = value
		end
	end

	return setmetatable({
		character = character,
		root = root,
		config = merged,
		pelvis = motorFor(character, spine.pelvis),
		-- R6 has one torso, so pelvis and chest are the same joint and it takes
		-- the whole lean. Nothing to split it across.
		chest = if spine.chest == spine.pelvis then nil else motorFor(character, spine.chest),
		weight = 1,
		lean = 0,
		bank = 0,
		_lastVelocity = Vector3.zero,
		_lastFacing = root.CFrame.LookVector,
		_connection = nil,
	}, Momentum)
end

function Momentum.setWeight(self: Momentum, weight: number)
	self.weight = math.clamp(weight, 0, 1)
end

function Momentum.update(self: Momentum, delta: number)
	if delta <= 0 then
		return
	end

	local velocity = self.root.AssemblyLinearVelocity
	local facing = self.root.CFrame.LookVector

	-- Acceleration along the direction of travel: positive is speeding up,
	-- negative is braking, and the sign is what flips the lean.
	local acceleration = (velocity - self._lastVelocity) / delta
	local heading = if velocity.Magnitude > 0.1 then velocity.Unit else facing
	local along = acceleration:Dot(heading)

	-- Cornering: how fast the facing is sweeping, times how fast we are going.
	-- Either alone is not a corner.
	local turn = self._lastFacing:Cross(facing).Y / delta
	local speed = Vector3.new(velocity.X, 0, velocity.Z).Magnitude

	local targetLean = math.clamp(
		-along * self.config.leanPerAcceleration,
		-self.config.maxLean,
		self.config.maxLean
	)
	local targetBank = math.clamp(
		turn * speed * self.config.bankPerTurn,
		-self.config.maxBank,
		self.config.maxBank
	)

	local alpha = math.clamp(delta / math.max(self.config.smoothing, 1e-3), 0, 1)
	self.lean += (targetLean - self.lean) * alpha
	self.bank += (targetBank - self.bank) * alpha

	self._lastVelocity = velocity
	self._lastFacing = facing

	self:_apply()
end

function Momentum._apply(self: Momentum)
	local lean = math.rad(self.lean * self.weight)
	local bank = math.rad(self.bank * self.weight)
	local share = if self.chest then self.config.pelvisShare else 1

	if self.pelvis then
		-- Multiplied onto the Animator's transform rather than replacing it, so
		-- the lean layers over whatever is playing instead of erasing it.
		self.pelvis.Transform = self.pelvis.Transform
			* CFrame.Angles(lean * share, 0, bank * share)
	end
	if self.chest then
		local rest = 1 - self.config.pelvisShare
		self.chest.Transform = self.chest.Transform
			* CFrame.Angles(lean * rest, 0, bank * rest)
	end
end

function Momentum.start(self: Momentum)
	if self._connection then
		return
	end
	self._connection = RunService.PreRender:Connect(function(delta)
		self:update(delta)
	end)
end

function Momentum.stop(self: Momentum)
	if self._connection then
		self._connection:Disconnect()
		self._connection = nil
	end
	self.lean = 0
	self.bank = 0
end

return Momentum
