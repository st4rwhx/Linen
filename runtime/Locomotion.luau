--!strict
--[[
	Locomotion driven by velocity, not by a state machine.

	Two things here, and the first is the one your feet notice.

	FOOT SLIDING is not an animation quality problem. A walk cycle covers a
	specific distance per turn — MotionData knows it, derived from how far apart
	the contact poses put the feet — and if the character's ground speed is not
	that, the feet must slide, no matter how good the clip is. The fix is
	arithmetic: play the clip at `groundSpeed / naturalSpeed`. Everything else
	in this module is downstream of that.

	BLENDING BY VELOCITY, not by timers. The weights of idle, walk and run are
	continuous functions of how fast the character is actually moving, so there
	are no transitions to trigger and none to get stuck in. Accelerate and the
	blend slides through walk into run because the speed did, not because a
	state machine decided.

	LAYERING comes free with Roblox's animation priorities: an upper-body track
	at a higher priority plays over the legs without either knowing about the
	other. The helper here just keeps the bookkeeping in one place.
]]

local RunService = game:GetService("RunService")

local MotionData = require(script.Parent.MotionData)

local Locomotion = {}
Locomotion.__index = Locomotion

export type Config = {
	--[[ Below this the character is standing still. Above zero because a
	     Humanoid's velocity is never exactly zero. ]]
	idleSpeed: number,
	--[[ Ground speed at which the run has fully taken over from the walk. Left
	     at 0 it is derived from the run's own natural speed, which is the
	     honest default: the run takes over where it stops needing to be
	     stretched. ]]
	runSpeed: number,
	--[[ Seconds for a weight to catch up. This is the only time constant in
	     the module, and it exists for smoothing, not for sequencing. ]]
	blendTime: number,
}

local DEFAULTS: Config = {
	idleSpeed = 0.6,
	runSpeed = 0,
	blendTime = 0.18,
}

export type Tracks = {
	idle: AnimationTrack?,
	walk: AnimationTrack?,
	run: AnimationTrack?,
}

export type Locomotion = typeof(setmetatable(
	{} :: {
		humanoid: Humanoid,
		root: BasePart,
		config: Config,
		tracks: Tracks,
		weights: { [string]: number },
		speed: number,
		_upper: { [string]: AnimationTrack },
		_connection: RBXScriptConnection?,
	},
	Locomotion
))

function Locomotion.new(humanoid: Humanoid, tracks: Tracks, config: Config?): Locomotion?
	local root = humanoid.RootPart
	if root == nil then
		return nil
	end

	local merged: Config = table.clone(DEFAULTS)
	if config then
		for key, value in config :: any do
			(merged :: any)[key] = value
		end
	end
	if merged.runSpeed <= 0 then
		local run = MotionData.gaits.run
		merged.runSpeed = if run then run.speed * 0.85 else 16
	end

	for name, track in tracks :: any do
		if track then
			(track :: AnimationTrack).Looped = true
			;(track :: AnimationTrack):Play(0.1, 0, 1)
			;(track :: AnimationTrack):AdjustWeight(if name == "idle" then 1 else 0, 0.1)
		end
	end

	return setmetatable({
		humanoid = humanoid,
		root = root,
		config = merged,
		tracks = tracks,
		weights = { idle = 1, walk = 0, run = 0 },
		speed = 0,
		_upper = {},
		_connection = nil,
	}, Locomotion)
end

function Locomotion.update(self: Locomotion, delta: number)
	if delta <= 0 then
		return
	end

	local velocity = self.root.AssemblyLinearVelocity
	self.speed = Vector3.new(velocity.X, 0, velocity.Z).Magnitude

	local walkSpeed = MotionData.gaits.walk
	local walkNatural = if walkSpeed then walkSpeed.speed else 7

	-- Three continuous weights, always summing to one. No transitions, so
	-- nothing to be halfway through when the player changes their mind.
	local idle, walk, run
	if self.speed <= self.config.idleSpeed then
		idle, walk, run = 1, 0, 0
	elseif self.speed <= walkNatural then
		local t = (self.speed - self.config.idleSpeed)
			/ math.max(walkNatural - self.config.idleSpeed, 1e-3)
		idle, walk, run = 1 - t, t, 0
	else
		local t = math.clamp(
			(self.speed - walkNatural) / math.max(self.config.runSpeed - walkNatural, 1e-3),
			0,
			1
		)
		idle, walk, run = 0, 1 - t, t
	end

	local alpha = math.clamp(delta / math.max(self.config.blendTime, 1e-3), 0, 1)
	self:_blend("idle", idle, alpha)
	self:_blend("walk", walk, alpha)
	self:_blend("run", run, alpha)

	-- The anti-slide. Each gait is played at whatever rate makes its own stride
	-- cover the ground the character is actually covering.
	if self.tracks.walk then
		self.tracks.walk:AdjustSpeed(MotionData.playbackFor("walk", self.speed))
	end
	if self.tracks.run then
		self.tracks.run:AdjustSpeed(MotionData.playbackFor("run", self.speed))
	end
end

function Locomotion._blend(self: Locomotion, name: string, target: number, alpha: number)
	local current = self.weights[name] or 0
	local blended = current + (target - current) * alpha
	self.weights[name] = blended

	local track = (self.tracks :: any)[name] :: AnimationTrack?
	if track then
		track:AdjustWeight(math.max(blended, 0.001), 0)
	end
end

--[[ Play something over the top — aiming, carrying, a reload — without
     disturbing the legs.

     Roblox resolves this by animation priority, so the upper-body clip must be
     authored to touch only the parts it needs. A clip that also keyframes the
     legs will override them at a higher priority, and the character will walk
     on stiff legs while insisting nothing is wrong. ]]
function Locomotion.playUpper(
	self: Locomotion,
	name: string,
	track: AnimationTrack,
	fade: number?
)
	local existing = self._upper[name]
	if existing then
		existing:Stop(fade or 0.15)
	end
	track.Priority = Enum.AnimationPriority.Action2
	track:Play(fade or 0.15)
	self._upper[name] = track
end

function Locomotion.stopUpper(self: Locomotion, name: string, fade: number?)
	local track = self._upper[name]
	if track then
		track:Stop(fade or 0.15)
		self._upper[name] = nil
	end
end

function Locomotion.start(self: Locomotion)
	if self._connection then
		return
	end
	self._connection = RunService.PreSimulation:Connect(function(delta)
		self:update(delta)
	end)
end

function Locomotion.stop(self: Locomotion)
	if self._connection then
		self._connection:Disconnect()
		self._connection = nil
	end
	for _, track in self.tracks :: any do
		if track then
			(track :: AnimationTrack):Stop(0.2)
		end
	end
	for name in self._upper do
		self:stopUpper(name)
	end
end

return Locomotion
