--!strict
--[[
	Is the character still standing up?

	The test a physicist would use, and the one Euphoria's balance behaviours
	are built on: project the centre of mass straight down and ask whether it
	lands inside the polygon the feet enclose. Inside, the character can push
	back and stay up. Outside, gravity has already won and the only question is
	how it falls.

	For a biped that polygon is thin — roughly the segment between the two feet,
	widened by the length of the soles — so this treats it as a capsule around
	that segment. That approximation is what lets it be a handful of vector
	operations per frame rather than a hull solve, and it is accurate where it
	matters, which is sideways.

	The output is a margin in studs: positive is how much room is left before
	toppling, negative is how far past the point of no return the body already
	is. Feed it to a ragdoll's drive strength and the character sags as it loses
	the argument instead of switching from animated to limp in one frame.
]]

local RunService = game:GetService("RunService")

local Balance = {}
Balance.__index = Balance

export type Config = {
	--[[ Half-width added around the foot-to-foot segment: sole length plus a
	     little, because a real foot can push against its toes. ]]
	footRadius: number,
	--[[ A foot within this of the ground counts as bearing weight. ]]
	contactDistance: number,
	--[[ Seconds of being outside the support before a fall is declared. A
	     stumble crosses the line and comes back; a fall does not. ]]
	graceTime: number,
	--[[ Margin at which the drive starts weakening, in studs. ]]
	softMargin: number,
}

local DEFAULTS: Config = {
	footRadius = 1.0,
	contactDistance = 1.2,
	graceTime = 0.28,
	softMargin = 0.9,
}

export type State = {
	--[[ Studs of room left. Negative means the centre of mass is outside. ]]
	margin: number,
	--[[ 1 while balanced, falling to 0 as the margin goes negative. Multiply a
	     ragdoll's drive strength by this. ]]
	support: number,
	centreOfMass: Vector3,
	grounded: number,
	falling: boolean,
}

export type Balance = typeof(setmetatable(
	{} :: {
		character: Model,
		humanoid: Humanoid,
		root: BasePart,
		feet: { BasePart },
		config: Config,
		state: State,
		_outside: number,
		_params: RaycastParams,
		_connection: RBXScriptConnection?,
		_onFall: ((State) -> ())?,
	},
	Balance
))

local FOOT_NAMES = { "LeftFoot", "RightFoot", "Left Leg", "Right Leg" }

local function flatten(v: Vector3): Vector3
	return Vector3.new(v.X, 0, v.Z)
end

local function distanceToSegment(point: Vector3, a: Vector3, b: Vector3): number
	local along = b - a
	local length = along.Magnitude
	if length < 1e-4 then
		return (point - a).Magnitude
	end
	local t = math.clamp((point - a):Dot(along) / (length * length), 0, 1)
	return (point - (a + along * t)).Magnitude
end

function Balance.new(character: Model, config: Config?): Balance?
	local humanoid = character:FindFirstChildOfClass("Humanoid")
	local root = character:FindFirstChild("HumanoidRootPart")
	if not (humanoid and root and root:IsA("BasePart")) then
		return nil
	end

	local feet: { BasePart } = {}
	for _, name in FOOT_NAMES do
		local part = character:FindFirstChild(name)
		if part and part:IsA("BasePart") then
			table.insert(feet, part)
		end
	end
	if #feet == 0 then
		return nil
	end

	local merged: Config = table.clone(DEFAULTS)
	if config then
		for key, value in config :: any do
			(merged :: any)[key] = value
		end
	end

	local params = RaycastParams.new()
	params.FilterType = Enum.RaycastFilterType.Exclude
	params.FilterDescendantsInstances = { character }
	params.IgnoreWater = true

	return setmetatable({
		character = character,
		humanoid = humanoid,
		root = root,
		feet = feet,
		config = merged,
		state = {
			margin = math.huge,
			support = 1,
			centreOfMass = root.Position,
			grounded = #feet,
			falling = false,
		},
		_outside = 0,
		_params = params,
		_connection = nil,
		_onFall = nil,
	}, Balance)
end

--[[ Mass-weighted, not the root's position. A character reaching overhead has
     a centre of mass well forward of its hips, and that difference is exactly
     what decides whether it topples. ]]
function Balance.centreOfMass(self: Balance): Vector3
	local total = 0
	local weighted = Vector3.zero
	for _, descendant in self.character:GetDescendants() do
		if descendant:IsA("BasePart") then
			local mass = descendant.AssemblyMass > 0 and descendant.AssemblyMass or descendant.Mass
			total += mass
			weighted += descendant.Position * mass
		end
	end
	return if total > 0 then weighted / total else self.root.Position
end

function Balance.evaluate(self: Balance, delta: number): State
	local com = self:centreOfMass()

	local grounded: { Vector3 } = {}
	for _, foot in self.feet do
		local result = workspace:Raycast(
			foot.Position,
			Vector3.yAxis * -(self.config.contactDistance + foot.Size.Y * 0.5),
			self._params
		)
		if result then
			table.insert(grounded, result.Position)
		end
	end

	local margin: number
	if #grounded == 0 then
		-- Nothing underneath: there is no support polygon to be inside of.
		margin = -math.huge
	elseif #grounded == 1 then
		margin = self.config.footRadius - (flatten(com) - flatten(grounded[1])).Magnitude
	else
		margin = self.config.footRadius - distanceToSegment(
			flatten(com),
			flatten(grounded[1]),
			flatten(grounded[#grounded])
		)
	end

	if margin < 0 then
		self._outside += delta
	else
		self._outside = 0
	end

	local falling = self._outside >= self.config.graceTime
	local support = math.clamp(
		(margin + self.config.softMargin) / math.max(self.config.softMargin, 1e-3),
		0,
		1
	)

	self.state = {
		margin = margin,
		support = support,
		centreOfMass = com,
		grounded = #grounded,
		falling = falling,
	}

	if falling and self._onFall then
		local callback = self._onFall
		self._onFall = nil
		callback(self.state)
	end

	return self.state
end

--[[ Fires once, the moment the character has definitively lost balance. Wire it
     to a ragdoll's `activate` with `state.support` as the strength: the arms go
     out and the body gives way rather than switching to limp in one frame. ]]
function Balance.onFall(self: Balance, callback: ((State) -> ())?)
	self._onFall = callback
	self._outside = 0
end

function Balance.start(self: Balance)
	if self._connection then
		return
	end
	self._connection = RunService.PostSimulation:Connect(function(delta)
		self:evaluate(delta)
	end)
end

function Balance.stop(self: Balance)
	if self._connection then
		self._connection:Disconnect()
		self._connection = nil
	end
end

return Balance
