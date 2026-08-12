--!strict
--[[
	Feet that sit on the ground the ground actually is.

	Stock Roblox locomotion plays a flat-ground walk cycle regardless of terrain,
	so on a slope one foot floats and the other sinks. This raycasts under each
	foot every frame and uses IKControl — Roblox's native runtime IK — to put
	the foot on what it hit, rolled to match the surface normal, with the pelvis
	dropped far enough that the longer leg can still reach.

	The order matters and is the part that is easy to get wrong: the pelvis has
	to move *before* the feet are solved. Solve the feet first and lowering the
	hips afterwards drags them straight back off the ground.

	Run this on the client, from PreRender: the Animator has written the pose by
	then, and IK is a correction on top of it. On the server it would fight
	replication and cost you a physics step per character.
]]

local RunService = game:GetService("RunService")

local FootPlanting = {}
FootPlanting.__index = FootPlanting

export type Config = {
	--[[ How far below the foot to look. Too short and a step down is missed;
	     too long and the foot reaches for the floor below a bridge. ]]
	traceDistance: number,
	--[[ How far above the foot the ray starts, so a foot already slightly
	     inside a surface still finds it. ]]
	traceRise: number,
	--[[ Distance from the ankle joint to the sole, in studs. R15's foot is
	     about one stud tall. ]]
	soleOffset: number,
	--[[ Studs per second the pelvis may move. Snapping it reads as a twitch. ]]
	pelvisSpeed: number,
	--[[ Beyond this the surface is a wall, not a floor, and rolling the foot
	     onto it looks broken. ]]
	maxSlopeAngle: number,
	--[[ Seconds for the IK to reach a new target. IKControl smooths for us. ]]
	smoothTime: number,
}

local DEFAULTS: Config = {
	traceDistance = 4,
	traceRise = 2,
	soleOffset = 0.5,
	pelvisSpeed = 6,
	maxSlopeAngle = 50,
	smoothTime = 0.06,
}

local FEET = {
	{ foot = "LeftFoot", chainRoot = "LeftUpperLeg" },
	{ foot = "RightFoot", chainRoot = "RightUpperLeg" },
}

export type FootState = {
	name: string,
	part: BasePart,
	control: IKControl,
	target: Attachment,
	grounded: boolean,
	drop: number,
}

export type FootPlanting = typeof(setmetatable(
	{} :: {
		character: Model,
		humanoid: Humanoid,
		root: BasePart,
		config: Config,
		feet: { FootState },
		baseHipHeight: number,
		pelvisDrop: number,
		weight: number,
		_params: RaycastParams,
		_connection: RBXScriptConnection?,
	},
	FootPlanting
))

--[[ R6 has one part per leg and no ankle, so there is nothing to solve: a
     single rigid leg cannot both reach the ground and keep its foot flat.
     This is R15 only, and says so rather than half-working. ]]
function FootPlanting.new(character: Model, config: Config?): FootPlanting?
	local humanoid = character:FindFirstChildOfClass("Humanoid")
	local root = character:FindFirstChild("HumanoidRootPart")
	if not (humanoid and root and root:IsA("BasePart")) then
		return nil
	end
	if character:FindFirstChild("LeftFoot") == nil then
		warn("FootPlanting: R15 only — an R6 leg has no ankle to roll.")
		return nil
	end

	local params = RaycastParams.new()
	params.FilterType = Enum.RaycastFilterType.Exclude
	params.FilterDescendantsInstances = { character }
	params.IgnoreWater = true

	local merged: Config = table.clone(DEFAULTS)
	if config then
		for key, value in config :: any do
			(merged :: any)[key] = value
		end
	end

	local self = setmetatable({
		character = character,
		humanoid = humanoid,
		root = root,
		config = merged,
		feet = {},
		baseHipHeight = humanoid.HipHeight,
		pelvisDrop = 0,
		weight = 1,
		_params = params,
		_connection = nil,
	}, FootPlanting)

	for _, entry in FEET do
		local part = character:FindFirstChild(entry.foot)
		local chainRoot = character:FindFirstChild(entry.chainRoot)
		if not (part and part:IsA("BasePart") and chainRoot and chainRoot:IsA("BasePart")) then
			continue
		end

		-- The target lives on the root part so it travels with the character,
		-- but we drive it in world space, which is what the raycast gives us.
		local target = Instance.new("Attachment")
		target.Name = `Linen_{entry.foot}_Target`
		target.Parent = root

		local control = Instance.new("IKControl")
		control.Name = `Linen_{entry.foot}_IK`
		control.Type = Enum.IKControlType.Transform
		control.ChainRoot = chainRoot
		control.EndEffector = part
		control.Target = target
		control.SmoothTime = merged.smoothTime
		control.Weight = 0
		control.Enabled = true
		control.Parent = humanoid

		table.insert(self.feet, {
			name = entry.foot,
			part = part,
			control = control,
			target = target,
			grounded = false,
			drop = 0,
		})
	end

	return self
end

function FootPlanting.start(self: FootPlanting)
	if self._connection then
		return
	end
	self._connection = RunService.PreRender:Connect(function(delta)
		self:update(delta)
	end)
end

function FootPlanting.stop(self: FootPlanting)
	if self._connection then
		self._connection:Disconnect()
		self._connection = nil
	end
	for _, foot in self.feet do
		foot.control.Weight = 0
	end
	self.humanoid.HipHeight = self.baseHipHeight
end

--[[ Fade the whole correction out. Airborne feet must not reach for the floor,
     and a ragdolling character must not be pulled about by its ankles. ]]
function FootPlanting.setWeight(self: FootPlanting, weight: number)
	self.weight = math.clamp(weight, 0, 1)
end

function FootPlanting.update(self: FootPlanting, delta: number)
	local state = self.humanoid:GetState()
	local airborne = state == Enum.HumanoidStateType.Freefall
		or state == Enum.HumanoidStateType.Jumping
		or state == Enum.HumanoidStateType.Physics
	local weight = if airborne then 0 else self.weight

	if weight <= 0 then
		for _, foot in self.feet do
			foot.control.Weight = math.max(foot.control.Weight - delta * 6, 0)
			foot.grounded = false
		end
		self.pelvisDrop = math.max(self.pelvisDrop - delta * self.config.pelvisSpeed, 0)
		self.humanoid.HipHeight = self.baseHipHeight - self.pelvisDrop
		return
	end

	-- Pass one: find the ground under each foot and note how far each would
	-- have to reach down.
	local deepest = 0
	for _, foot in self.feet do
		local origin = foot.part.Position + Vector3.yAxis * self.config.traceRise
		local result = workspace:Raycast(
			origin,
			Vector3.yAxis * -(self.config.traceRise + self.config.traceDistance),
			self._params
		)

		foot.grounded = false
		if result then
			local slope = math.deg(math.acos(math.clamp(result.Normal:Dot(Vector3.yAxis), -1, 1)))
			if slope <= self.config.maxSlopeAngle then
				foot.grounded = true
				local soleY = foot.part.Position.Y - self.config.soleOffset
				foot.drop = math.max(soleY - result.Position.Y, 0)
				deepest = math.max(deepest, foot.drop)
				foot.target.WorldCFrame = self:_soleCFrame(foot, result)
			end
		end
	end

	-- Pass two: drop the pelvis so the leg that has furthest to reach still
	-- can. This must happen before the feet are solved, hence two passes: lower
	-- the hips after solving and the feet come straight back off the ground.
	local wanted = math.min(deepest, self.config.traceDistance)
	local step = self.config.pelvisSpeed * delta
	self.pelvisDrop += math.clamp(wanted - self.pelvisDrop, -step, step)
	self.humanoid.HipHeight = self.baseHipHeight - self.pelvisDrop

	for _, foot in self.feet do
		local goal = if foot.grounded then weight else 0
		foot.control.Weight += math.clamp(goal - foot.control.Weight, -delta * 6, delta * 6)
	end
end

--[[ Where the foot should sit: on the surface, rolled onto its normal, keeping
     the toe pointing the way the animation had it. ]]
function FootPlanting._soleCFrame(
	self: FootPlanting,
	foot: FootState,
	result: RaycastResult
): CFrame
	local normal = result.Normal
	local forward = foot.part.CFrame.LookVector
	-- Re-orthogonalise the animated facing against the surface rather than
	-- replacing it, so the foot rolls onto the slope without also turning.
	local right = forward:Cross(normal)
	if right.Magnitude < 1e-3 then
		right = foot.part.CFrame.RightVector
	end
	local flattened = normal:Cross(right.Unit)

	local position = result.Position + normal * self.config.soleOffset
	return CFrame.lookAlong(position, flattened.Unit, normal)
end

function FootPlanting.destroy(self: FootPlanting)
	self:stop()
	for _, foot in self.feet do
		foot.control:Destroy()
		foot.target:Destroy()
	end
	table.clear(self.feet)
end

return FootPlanting
