--!strict
--[[
	Active ragdoll: a body that is simulated but still *trying*.

	A passive ragdoll disables the joints and lets the character drop. Euphoria's
	whole point is that the character keeps attempting to hold a pose while
	physics acts on it, so this drives every joint back towards the pose the
	animation would have produced, with a strength you can turn down per joint.
	Turn it to zero and you get the sack of bricks; leave it high and the
	character absorbs a shove and recovers.

	Two details do most of the work:

	  * elbows and knees are HingeConstraints, not cones. A ball-and-socket
	    elbow bends sideways, and under an impulse it will;
	  * the joint the character hangs from is welded. The root part is the
	    physics capsule, not a body part, and letting it pivot folds the
	    character in half.

	Both come from RigLimits, generated from the same rig definitions the
	exporter uses, so the physics rig cannot drift from the animation rig.

	ASSUMPTION worth verifying in your place: this reads `Motor6D.Transform` for
	the animated pose while the motor is disabled. The Animator is expected to
	keep writing it. If your build stops updating Transform on a disabled motor,
	call `setPoseSource` with a function reading from an invisible puppet rig
	that plays the same track — same maths, one more rig.

	NETWORK OWNERSHIP: a ragdolling character's parts must have a single owner
	or the simulation fights itself across the wire. Call `setNetworkOwner`
	after `activate` — nil for server-authoritative (right for NPCs and for
	anything a player could exploit), the player for responsiveness on their own
	character.
]]

local RunService = game:GetService("RunService")

local RigLimits = require(script.Parent.RigLimits)

local Ragdoll = {}
Ragdoll.__index = Ragdoll

export type JointState = {
	name: string,
	motor: Motor6D,
	part0: BasePart,
	part1: BasePart,
	socket: Constraint?,
	weld: WeldConstraint?,
	driveAttachment: Attachment?,
	align: AlignOrientation?,
	limit: RigLimits.JointLimit,
	blend: number,
}

export type Ragdoll = typeof(setmetatable(
	{} :: {
		character: Model,
		humanoid: Humanoid,
		rigName: string,
		joints: { [string]: JointState },
		active: boolean,
		_connection: RBXScriptConnection?,
		_poseSource: ((JointState) -> CFrame)?,
		_collidable: { [BasePart]: boolean },
	},
	Ragdoll
))

local function attachmentFor(part: BasePart, name: string, cframe: CFrame): Attachment
	local existing = part:FindFirstChild(name)
	if existing and existing:IsA("Attachment") then
		existing.CFrame = cframe
		return existing
	end
	local attachment = Instance.new("Attachment")
	attachment.Name = name
	attachment.CFrame = cframe
	attachment.Parent = part
	return attachment
end

--[[ Build the constraint set once, disabled. Doing this at the moment of a hit
     costs a frame of stutter exactly when the player is looking. ]]
function Ragdoll.new(character: Model): Ragdoll?
	local humanoid = character:FindFirstChildOfClass("Humanoid")
	local rigName = RigLimits.detect(character)
	if humanoid == nil or rigName == nil then
		warn(`Ragdoll: {character.Name} is neither an R15 nor an R6 rig`)
		return nil
	end

	local spec = assert(RigLimits.get(rigName))
	local self = setmetatable({
		character = character,
		humanoid = humanoid,
		rigName = rigName,
		joints = {},
		active = false,
		_connection = nil,
		_poseSource = nil,
		_collidable = {},
	}, Ragdoll)

	for partName, jointName in spec.joints do
		local part1 = character:FindFirstChild(partName)
		if not (part1 and part1:IsA("BasePart")) then
			continue
		end
		local motor = part1:FindFirstChild(jointName)
		if not (motor and motor:IsA("Motor6D") and motor.Part0 and motor.Part1) then
			continue
		end

		local limit = spec.limits[jointName]
		local state: JointState = {
			name = jointName,
			motor = motor,
			part0 = motor.Part0 :: BasePart,
			part1 = motor.Part1 :: BasePart,
			socket = nil,
			weld = nil,
			driveAttachment = nil,
			align = nil,
			limit = limit,
			blend = 0,
		}
		self:_buildConstraint(state)
		self.joints[jointName] = state
		self._collidable[part1] = part1.CanCollide
	end

	return self
end

function Ragdoll._buildConstraint(self: Ragdoll, state: JointState)
	local motor = state.motor
	local limit = state.limit

	if limit.kind == "fixed" then
		-- The root: welded rather than constrained, so the body hangs from a
		-- rigid capsule instead of pivoting about its own middle.
		local weld = Instance.new("WeldConstraint")
		weld.Name = `Linen_{state.name}_Weld`
		weld.Part0 = state.part0
		weld.Part1 = state.part1
		weld.Enabled = false
		weld.Parent = state.part1
		state.weld = weld
		return
	end

	-- The Motor6D's C0 and C1 *are* the joint pivot, expressed in each part's
	-- own space. Reusing them is what puts the physical joint exactly where the
	-- animated one was, instead of a hand-guessed offset.
	local a0 = attachmentFor(state.part0, `Linen_{state.name}_A0`, motor.C0)
	local a1 = attachmentFor(state.part1, `Linen_{state.name}_A1`, motor.C1)

	if limit.kind == "hinge" then
		local hinge = Instance.new("HingeConstraint")
		hinge.Name = `Linen_{state.name}`
		hinge.Attachment0 = a0
		hinge.Attachment1 = a1
		hinge.LimitsEnabled = true
		hinge.LowerAngle = limit.lower
		hinge.UpperAngle = limit.upper
		hinge.ActuatorType = Enum.ActuatorType.None
		hinge.Enabled = false
		hinge.Parent = state.part1
		state.socket = hinge
	else
		local socket = Instance.new("BallSocketConstraint")
		socket.Name = `Linen_{state.name}`
		socket.Attachment0 = a0
		socket.Attachment1 = a1
		socket.LimitsEnabled = true
		socket.UpperAngle = limit.swing
		socket.TwistLimitsEnabled = true
		socket.TwistLowerAngle = limit.twistLower
		socket.TwistUpperAngle = limit.twistUpper
		socket.Enabled = false
		socket.Parent = state.part1
		state.socket = socket
	end

	-- The drive. AlignOrientation pulls the child's own orientation onto a
	-- target attachment carried by the parent, and that target is moved every
	-- frame to wherever the animation says the child should be. That is the
	-- whole "still trying" behaviour, in one constraint.
	local driveTarget = attachmentFor(state.part0, `Linen_{state.name}_Drive`, motor.C0)
	local driveSelf = attachmentFor(state.part1, `Linen_{state.name}_Self`, CFrame.identity)

	local align = Instance.new("AlignOrientation")
	align.Name = `Linen_{state.name}_Align`
	align.Mode = Enum.OrientationAlignmentMode.TwoAttachment
	align.Attachment0 = driveSelf
	align.Attachment1 = driveTarget
	align.RigidityEnabled = false
	align.Responsiveness = limit.responsiveness
	align.MaxTorque = limit.maxTorque
	align.Enabled = false
	align.Parent = state.part1

	state.driveAttachment = driveTarget
	state.align = align
end

--[[ Hand back the pose the animation wants for a joint, as a CFrame relative to
     Part0. Override when Motor6D.Transform is not usable in your build. ]]
function Ragdoll.setPoseSource(self: Ragdoll, source: ((JointState) -> CFrame)?)
	self._poseSource = source
end

function Ragdoll._targetCFrame(self: Ragdoll, state: JointState): CFrame
	if self._poseSource then
		return self._poseSource(state)
	end
	-- Motor6D semantics: Part1 = Part0 * C0 * Transform * C1:Inverse(). The
	-- drive attachment sits at exactly that, so aligning the child to it
	-- reproduces the animated pose when nothing is pushing back.
	local motor = state.motor
	return motor.C0 * motor.Transform * motor.C1:Inverse()
end

--[[ Go physical. `strength` in [0, 1] scales how hard the body fights back:
     1 keeps it near the animation and merely disturbed, 0 lets it collapse.
     `joints` restricts the change to named joints, which is how you get an
     upper body that reacts to a shot while the legs keep walking. ]]
function Ragdoll.activate(self: Ragdoll, strength: number, joints: { string }?)
	strength = math.clamp(strength, 0, 1)

	local selected: { [string]: boolean }? = nil
	if joints then
		selected = {}
		for _, name in joints do
			(selected :: any)[name] = true
		end
	end

	for name, state in self.joints do
		if selected and not selected[name] then
			continue
		end
		state.blend = 1
		state.motor.Enabled = false
		if state.weld then
			state.weld.Enabled = true
		end
		if state.socket then
			state.socket.Enabled = true
		end
		if state.align then
			state.align.Enabled = strength > 0
			state.align.MaxTorque = state.limit.maxTorque * strength
			state.align.Responsiveness = state.limit.responsiveness * math.max(strength, 0.05)
		end
		state.part1.CanCollide = true
	end

	if not self.active then
		self.active = true
		self.humanoid:ChangeState(Enum.HumanoidStateType.Physics)
		self.humanoid.PlatformStand = true
		-- PreSimulation runs after the Animator has written Transform for this
		-- step, so the drive targets are one read behind nothing.
		self._connection = RunService.PreSimulation:Connect(function()
			self:_updateDrives()
		end)
	end
end

function Ragdoll._updateDrives(self: Ragdoll)
	for _, state in self.joints do
		if state.blend > 0 and state.driveAttachment and state.align and state.align.Enabled then
			state.driveAttachment.CFrame = self:_targetCFrame(state)
		end
	end
end

--[[ Back to animation. The character snaps to wherever the Animator wants it,
     so call this from a get-up animation rather than mid-fall. ]]
function Ragdoll.deactivate(self: Ragdoll)
	for _, state in self.joints do
		state.blend = 0
		if state.socket then
			state.socket.Enabled = false
		end
		if state.weld then
			state.weld.Enabled = false
		end
		if state.align then
			state.align.Enabled = false
		end
		state.part1.CanCollide = self._collidable[state.part1] or false
		state.motor.Enabled = true
	end

	if self._connection then
		self._connection:Disconnect()
		self._connection = nil
	end
	self.active = false
	self.humanoid.PlatformStand = false
	self.humanoid:ChangeState(Enum.HumanoidStateType.GettingUp)
end

--[[ A hit. Applied at a world position so a shot to the shoulder spins the
     character rather than shoving it bodily backwards — the impulse's lever arm
     is most of what makes a reaction read as a hit and not a push. ]]
function Ragdoll.impulse(self: Ragdoll, part: BasePart, impulse: Vector3, worldPosition: Vector3?)
	if worldPosition then
		part:ApplyImpulseAtPosition(impulse, worldPosition)
	else
		part:ApplyImpulse(impulse)
	end
end

--[[ Set one owner for every simulated part. Without this the server and the
     owning client both integrate the ragdoll and it jitters. ]]
function Ragdoll.setNetworkOwner(self: Ragdoll, player: Player?)
	if not RunService:IsServer() then
		return
	end
	for _, descendant in self.character:GetDescendants() do
		if descendant:IsA("BasePart") and not descendant.Anchored then
			pcall(function()
				descendant:SetNetworkOwner(player)
			end)
		end
	end
end

function Ragdoll.destroy(self: Ragdoll)
	if self.active then
		self:deactivate()
	end
	for _, state in self.joints do
		if state.socket then
			state.socket:Destroy()
		end
		if state.weld then
			state.weld:Destroy()
		end
		if state.align then
			state.align:Destroy()
		end
	end
	table.clear(self.joints)
end

return Ragdoll
