--!strict
--[[
	Secondary motion: the cheapest route to the Euphoria look on a stock rig.

	R15 has fifteen parts and one spine joint, so you cannot get there by adding
	articulation. But most of what reads as "alive" in a Rockstar character is
	not articulation — it is *timing between joints*, and that costs nothing:

	  * DRAG. Every joint down a chain lags its parent slightly. A hand arrives
	    after the forearm, which arrives after the upper arm. This is overlapping
	    action, the animation principle that separates hand-animated from
	    interpolated, and applying it procedurally makes an ordinary canned clip
	    look authored. It is the single highest-value thing in this file.

	  * IMPACT WAVES. A hit does not move the whole body at once; it travels out
	    from the point of contact, arriving later and weaker at each joint. This
	    is the Euphoria signature, and it does not need physics at all — which
	    matters, because it works on a character you do not want to ragdoll.

	  * GAZE. Characters look at what threatens them, and the head leads the
	    body. Nothing buys more perceived intelligence per line.

	  * TREMOR. Small, slow noise scaled by exertion. Absence of it is why a
	    held pose reads as a statue.

	All of it is applied by multiplying the Motor6D transforms the Animator has
	already written, from PreRender. It layers over any animation without
	knowing anything about it.
]]

local RunService = game:GetService("RunService")

local RigLimits = require(script.Parent.RigLimits)

local Secondary = {}
Secondary.__index = Secondary

export type Config = {
	--[[ Seconds a joint lags its parent. Small: past about 0.12 the character
	     stops looking heavy and starts looking underwater. ]]
	dragTime: number,
	--[[ How much of the lag actually shows, 0-1. ]]
	dragWeight: number,
	--[[ Joints per second an impact wave travels outward. ]]
	waveSpeed: number,
	--[[ Fraction of the amplitude surviving each joint it crosses. ]]
	waveFalloff: number,
	--[[ Degrees of head turn per unit of gaze weight, and how much of it the
	     chest picks up. Eyes lead, then head, then shoulders. ]]
	gazeMaxYaw: number,
	gazeMaxPitch: number,
	gazeChestShare: number,
	gazeSmoothing: number,
	tremorDegrees: number,
	tremorRate: number,
}

local DEFAULTS: Config = {
	dragTime = 0.055,
	dragWeight = 0.8,
	waveSpeed = 14,
	waveFalloff = 0.62,
	gazeMaxYaw = 62,
	gazeMaxPitch = 28,
	gazeChestShare = 0.35,
	gazeSmoothing = 0.16,
	tremorDegrees = 0.35,
	tremorRate = 1.3,
}

type JointNode = {
	name: string,
	motor: Motor6D,
	--[[ Distance from the root in joints. Both the drag depth and how late an
	     impact wave reaches this joint. ]]
	depth: number,
	--[[ The lagging copy of the animated rotation. ]]
	dragged: CFrame,
	--[[ Live impact contribution, decaying. ]]
	impulse: CFrame,
	impulseEnergy: number,
	phase: number,
}

type Impact = {
	origin: number,
	elapsed: number,
	amplitude: number,
	axis: Vector3,
	decay: number,
}

export type Secondary = typeof(setmetatable(
	{} :: {
		character: Model,
		rigName: string,
		config: Config,
		nodes: { JointNode },
		head: Motor6D?,
		chest: Motor6D?,
		gazeTarget: Vector3?,
		gazeYaw: number,
		gazePitch: number,
		exertion: number,
		weight: number,
		impacts: { Impact },
		_root: BasePart,
		_clock: number,
		_connection: RBXScriptConnection?,
	},
	Secondary
))

local function depthOf(spec: RigLimits.RigSpec, partName: string): number
	local depth = 0
	local current = partName
	while spec.parents[current] do
		current = spec.parents[current]
		depth += 1
	end
	return depth
end

function Secondary.new(character: Model, config: Config?): Secondary?
	local rigName = RigLimits.detect(character)
	local root = character:FindFirstChild("HumanoidRootPart")
	if rigName == nil or not (root and root:IsA("BasePart")) then
		return nil
	end
	local spec = assert(RigLimits.get(rigName))

	local merged: Config = table.clone(DEFAULTS)
	if config then
		for key, value in config :: any do
			(merged :: any)[key] = value
		end
	end

	local self = setmetatable({
		character = character,
		rigName = rigName,
		config = merged,
		nodes = {},
		head = nil,
		chest = nil,
		gazeTarget = nil,
		gazeYaw = 0,
		gazePitch = 0,
		exertion = 0,
		weight = 1,
		impacts = {},
		_root = root,
		_clock = 0,
		_connection = nil,
	}, Secondary)

	for partName, jointName in spec.joints do
		local part = character:FindFirstChild(partName)
		if not (part and part:IsA("BasePart")) then
			continue
		end
		local motor = part:FindFirstChild(jointName)
		if not (motor and motor:IsA("Motor6D")) then
			continue
		end
		table.insert(self.nodes, {
			name = jointName,
			motor = motor,
			depth = depthOf(spec, partName),
			dragged = motor.Transform,
			impulse = CFrame.identity,
			impulseEnergy = 0,
			-- Offsetting each joint's tremor phase keeps the body from
			-- breathing as one rigid block.
			phase = math.random() * math.pi * 2,
		})
		if partName == "Head" then
			self.head = motor
		elseif partName == "UpperTorso" or partName == "Torso" then
			self.chest = motor
		end
	end

	-- Shallow joints first, so a parent's drag is already resolved when its
	-- child reads it.
	table.sort(self.nodes, function(a, b)
		return a.depth < b.depth
	end)

	return self
end

function Secondary.setWeight(self: Secondary, weight: number)
	self.weight = math.clamp(weight, 0, 1)
end

--[[ 0 is rested, 1 is spent. Drives the tremor: a character who has just
     sprinted or is bleeding should not hold a pose as cleanly as one who
     has not. ]]
function Secondary.setExertion(self: Secondary, exertion: number)
	self.exertion = math.clamp(exertion, 0, 1)
end

--[[ Look here. Pass nil to release, and the head returns to neutral on its own
     rather than snapping. ]]
function Secondary.lookAt(self: Secondary, worldPosition: Vector3?)
	self.gazeTarget = worldPosition
end

--[[ Something hit `partName` hard enough to be felt. The disturbance starts
     there and travels outward through the joint chain, arriving later and
     weaker the further it goes — which is what makes a shoulder hit read as a
     shoulder hit rather than the whole body twitching at once.

     `direction` is the world-space push; `amplitude` is in degrees at the
     point of impact. ]]
function Secondary.impact(
	self: Secondary,
	partName: string,
	direction: Vector3,
	amplitude: number
)
	local spec = RigLimits.get(self.rigName)
	if spec == nil or spec.joints[partName] == nil then
		return
	end

	-- The rotation axis is perpendicular to the push, in the character's own
	-- frame: a shove from the front pitches the body, one from the side rolls
	-- it. Taking the push direction itself would spin the character about the
	-- axis it was hit along, which never happens to a body.
	local localPush = self._root.CFrame:VectorToObjectSpace(direction)
	local axis = Vector3.new(-localPush.Z, 0, localPush.X)
	if axis.Magnitude < 1e-3 then
		axis = Vector3.xAxis
	end

	table.insert(self.impacts, {
		origin = depthOf(spec, partName),
		elapsed = 0,
		amplitude = math.rad(amplitude),
		axis = axis.Unit,
		decay = 4.5,
	})
end

function Secondary.update(self: Secondary, delta: number)
	if delta <= 0 or self.weight <= 0 then
		return
	end
	self._clock += delta

	self:_advanceImpacts(delta)
	self:_updateGaze(delta)

	local dragAlpha = math.clamp(delta / math.max(self.config.dragTime, 1e-3), 0, 1)
	local tremor = math.rad(self.config.tremorDegrees) * self.exertion * self.weight

	for _, node in self.nodes do
		local animated = node.motor.Transform
		local result = animated

		-- Drag. Deeper joints lag more, so the lag accumulates down a limb the
		-- way a real one whips.
		if self.config.dragWeight > 0 and node.depth > 0 then
			local perJoint = math.clamp(dragAlpha / (1 + node.depth * 0.35), 0, 1)
			node.dragged = node.dragged:Lerp(animated, perJoint)
			result = animated:Lerp(node.dragged, self.config.dragWeight * self.weight)
		else
			node.dragged = animated
		end

		if node.impulseEnergy > 0 then
			result = result * node.impulse
		end

		if tremor > 0 then
			local t = self._clock * self.config.tremorRate + node.phase
			result = result
				* CFrame.Angles(math.sin(t) * tremor, math.sin(t * 1.7) * tremor, 0)
		end

		node.motor.Transform = result
	end

	self:_applyGaze()
end

function Secondary._advanceImpacts(self: Secondary, delta: number)
	for _, node in self.nodes do
		node.impulseEnergy = 0
		node.impulse = CFrame.identity
	end

	local index = #self.impacts
	while index >= 1 do
		local impact = self.impacts[index]
		impact.elapsed += delta
		impact.amplitude *= math.exp(-impact.decay * delta)

		if impact.amplitude < math.rad(0.05) then
			table.remove(self.impacts, index)
		else
			local front = impact.elapsed * self.config.waveSpeed
			for _, node in self.nodes do
				local distance = math.abs(node.depth - impact.origin)
				-- The wave has not reached this joint yet.
				if distance > front then
					continue
				end
				local strength = impact.amplitude
					* self.config.waveFalloff ^ distance
				if strength > math.rad(0.02) then
					node.impulseEnergy += strength
					node.impulse = node.impulse
						* CFrame.fromAxisAngle(impact.axis, strength)
				end
			end
		end
		index -= 1
	end
end

function Secondary._updateGaze(self: Secondary, delta: number)
	local wantedYaw, wantedPitch = 0, 0

	if self.gazeTarget then
		local toTarget = self._root.CFrame:PointToObjectSpace(self.gazeTarget)
		local flat = Vector3.new(toTarget.X, 0, toTarget.Z)
		if flat.Magnitude > 1e-3 then
			wantedYaw = math.deg(math.atan2(-toTarget.X, -toTarget.Z))
			wantedPitch = math.deg(math.atan2(toTarget.Y, flat.Magnitude))
		end
		-- Past the limit the character would have to turn its body, and a head
		-- that keeps rotating past its stop is the classic owl-neck artefact.
		wantedYaw = math.clamp(wantedYaw, -self.config.gazeMaxYaw, self.config.gazeMaxYaw)
		wantedPitch = math.clamp(
			wantedPitch,
			-self.config.gazeMaxPitch,
			self.config.gazeMaxPitch
		)
	end

	local alpha = math.clamp(delta / math.max(self.config.gazeSmoothing, 1e-3), 0, 1)
	self.gazeYaw += (wantedYaw - self.gazeYaw) * alpha
	self.gazePitch += (wantedPitch - self.gazePitch) * alpha
end

function Secondary._applyGaze(self: Secondary)
	if math.abs(self.gazeYaw) < 0.05 and math.abs(self.gazePitch) < 0.05 then
		return
	end
	local share = self.config.gazeChestShare
	local weight = self.weight

	if self.chest then
		self.chest.Transform = self.chest.Transform
			* CFrame.Angles(
				math.rad(-self.gazePitch * share * weight),
				math.rad(self.gazeYaw * share * weight),
				0
			)
	end
	if self.head then
		local rest = if self.chest then 1 - share else 1
		self.head.Transform = self.head.Transform
			* CFrame.Angles(
				math.rad(-self.gazePitch * rest * weight),
				math.rad(self.gazeYaw * rest * weight),
				0
			)
	end
end

function Secondary.start(self: Secondary)
	if self._connection then
		return
	end
	-- After the Animator, before rendering: this is a correction on the pose,
	-- not a replacement for it.
	self._connection = RunService.PreRender:Connect(function(delta)
		self:update(delta)
	end)
end

function Secondary.stop(self: Secondary)
	if self._connection then
		self._connection:Disconnect()
		self._connection = nil
	end
	table.clear(self.impacts)
end

return Secondary
